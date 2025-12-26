from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from oqe.cache import SQLiteCache, default_cache_path, make_cache_key
from oqe.polygon.client import OptionChainQuery, PolygonClient
from oqe.polygon.helpers import ns_to_utc_iso
from oqe.polygon.http import PolygonError, PolygonNotFoundError
from oqe.polygon.normalise import (
    option_contract_from_snapshot_row,
    option_greeks_from_snapshot_row,
    option_quote_from_snapshot_row,
)
from oqe.tool_schemas import (
    GetOptionGreeksInput,
    GetOptionGreeksOutput,
    GetOptionQuotesInput,
    GetOptionQuotesOutput,
    GetUnderlyingSnapshotInput,
    GetUnderlyingSnapshotOutput,
    ListOptionContractsInput,
    ListOptionContractsOutput,
    ToolMeta,
    WarningCode,
)

CACHE_TTL_LATEST_SECONDS = 30
CACHE_TTL_HISTORICAL_SECONDS = (
    24 * 60 * 60
)  # not used by this tool (no asof support), but keeping for consistency

_OPTION_UNDERLYING_RE = re.compile(r"^O:([A-Z]+)\d{6}[CP]\d+")


def _dump_model(m, *, exclude: set[str] | None = None) -> dict:
    exclude = exclude or set()
    if hasattr(m, "model_dump"):  # pydantic v2
        # mode="json" converts datetime -> ISO strings, etc.
        return m.model_dump(mode="json", exclude_none=True, exclude=exclude)
    # pydantic v1: .json() handles datetime -> ISO; round-trip back to dict
    return json.loads(m.json(exclude_none=True, exclude=exclude))


def _underlying_from_option_symbol(sym: str) -> str:
    m = _OPTION_UNDERLYING_RE.match(sym.upper())
    if not m:
        raise ValueError(f"Cannot parse underlying from option_symbol: {sym}")
    return m.group(1)


def _meta(
    tool: str,
    asof: datetime | None,
    warnings: list[WarningCode],
    *,
    primary_source: str = "polygon",
) -> ToolMeta:
    return ToolMeta(
        tool=tool,
        generated_at=datetime.now(UTC),
        asof=asof,
        primary_source=primary_source,
        warnings=warnings,
    )


@lru_cache(maxsize=1)
def _get_cache() -> SQLiteCache:
    # One shared connection per process; path is env-overridable via OQE_CACHE_PATH
    return SQLiteCache(default_cache_path())


def _stable_json_dumps(obj: Any) -> str:
    # Deterministic JSON for cache storage (sort keys, compact)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def get_underlying_snapshot(inp: GetUnderlyingSnapshotInput) -> GetUnderlyingSnapshotOutput:
    # Warnings that are request-specific (not cached)
    req_warnings: list[WarningCode] = []
    if inp.asof is not None:
        # Polygon snapshot endpoints here are "latest"; historical-asof comes in Part 4/5.
        req_warnings.append("VENDOR_LIMIT")

    tool_name = "get_underlying_snapshot"
    effective_asof = None  # this endpoint is latest-only

    # Key excludes inp.asof so "asof requested but unsupported" still reuses latest cache
    tool_inputs = _dump_model(inp, exclude={"asof"})
    key, asof_norm, inputs_json = make_cache_key(tool_name, tool_inputs, asof=effective_asof)

    cache = _get_cache()

    # --- Cache hit ---
    rec = cache.get(key)
    if rec is not None:
        cached = json.loads(rec.response_json)
        snapshot = cached["snapshot"]
        base_warnings: list[WarningCode] = cached.get("warnings", [])
        warnings = [*base_warnings, *req_warnings]

        return GetUnderlyingSnapshotOutput(
            meta=_meta(tool_name, inp.asof, warnings, primary_source="cache"),
            snapshot=snapshot,
        )

    # --- Cache miss: call Polygon as you currently do ---
    base_warnings: list[WarningCode] = []

    pc = PolygonClient()
    try:
        _first, rows = pc.list_option_chain_snapshot(
            inp.ticker,
            OptionChainQuery(limit=1, max_pages=1),
        )
        if not rows:
            base_warnings.append("NO_RESULTS")
            raise PolygonNotFoundError(f"No option snapshot results for {inp.ticker}")

        ua = rows[0].get("underlying_asset") or {}
        spot = ua.get("price")
        last_updated_ns = ua.get("last_updated")
        timeframe = ua.get("timeframe")

        if timeframe and str(timeframe).upper() != "REAL-TIME":
            base_warnings.append("STALE_DATA")

        if spot is None:
            base_warnings.append("PARTIAL_DATA")
            raise PolygonError(f"Missing underlying_asset.price for {inp.ticker}")

        snapshot = {
            "ticker": inp.ticker,
            "spot": float(spot),
            "ts": ns_to_utc_iso(int(last_updated_ns)) if last_updated_ns is not None else None,
            "source": "polygon",  # origin of data; served-from is in ToolMeta.primary_source
        }

        # Cache only deterministic payload (snapshot + base warnings)
        cache.set(
            key=key,
            tool=tool_name,
            asof=asof_norm,
            inputs_json=inputs_json,
            response_json=_stable_json_dumps({"snapshot": snapshot, "warnings": base_warnings}),
            ttl_seconds=CACHE_TTL_LATEST_SECONDS,
        )

        warnings = [*base_warnings, *req_warnings]
        return GetUnderlyingSnapshotOutput(
            meta=_meta(tool_name, inp.asof, warnings, primary_source="polygon"),
            snapshot=snapshot,
        )
    finally:
        pc.close()


def list_option_contracts(inp: ListOptionContractsInput) -> ListOptionContractsOutput:
    warnings: list[WarningCode] = []

    contract_type = None
    if inp.right == "C":
        contract_type = "call"
    elif inp.right == "P":
        contract_type = "put"

    expiry_str = inp.expiry.isoformat() if inp.expiry is not None else None

    # Page sizing: Polygon returns paginated results; fetch enough pages to satisfy limit.
    per_page = min(1000, max(250, inp.limit))
    max_pages = min(50, (inp.limit // per_page) + 2)

    pc = PolygonClient()
    try:
        _first, rows = pc.list_option_chain_snapshot(
            inp.ticker,
            OptionChainQuery(
                contract_type=contract_type,
                expiration_date=expiry_str,
                limit=per_page,
                max_pages=max_pages,
            ),
        )

        contracts = [
            option_contract_from_snapshot_row(r, fallback_underlying=inp.ticker) for r in rows
        ]

        # strike range filter (Polygon snapshot doesn’t support min/max directly)
        if inp.strike_min is not None:
            contracts = [c for c in contracts if c.strike >= inp.strike_min]
        if inp.strike_max is not None:
            contracts = [c for c in contracts if c.strike <= inp.strike_max]

        if not contracts:
            warnings.append("NO_RESULTS")

        if len(contracts) > inp.limit:
            warnings.append("VENDOR_LIMIT")
            contracts = contracts[: inp.limit]

        return ListOptionContractsOutput(
            meta=_meta("list_option_contracts", None, warnings),
            contracts=contracts,
        )
    finally:
        pc.close()


def get_option_quotes(inp: GetOptionQuotesInput) -> GetOptionQuotesOutput:
    # request-specific warnings (not cached)
    req_warnings: list[WarningCode] = []
    if inp.asof is not None:
        req_warnings.append("VENDOR_LIMIT")

    tool_name = "get_option_quotes"
    effective_asof = None  # snapshot endpoint is latest-only

    # cache key excludes asof so "asof requested but unsupported" reuses latest cache
    tool_inputs = _dump_model(inp, exclude={"asof"})
    key, asof_norm, inputs_json = make_cache_key(tool_name, tool_inputs, asof=effective_asof)

    cache = _get_cache()

    # --- Cache hit ---
    rec = cache.get(key)
    if rec is not None:
        cached = json.loads(rec.response_json)
        base_warnings: list[WarningCode] = cached.get("warnings", [])
        warnings = [*base_warnings, *req_warnings]
        qb = cached.get("quotes_by_symbol", {})
        quotes = [qb[s] for s in inp.option_symbols if s in qb]

        return GetOptionQuotesOutput(
            meta=_meta(tool_name, inp.asof, warnings, primary_source="cache"),
            quotes=quotes,
        )

    # --- Cache miss: vendor ---
    base_warnings: list[WarningCode] = []

    by_underlying: dict[str, list[str]] = defaultdict(list)
    for sym in inp.option_symbols:
        by_underlying[_underlying_from_option_symbol(sym)].append(sym)

    pc = PolygonClient()
    try:
        out_map: dict[str, Any] = {}
        partial = False

        for underlying, syms in by_underlying.items():
            # IMPORTANT: dedupe to avoid duplicated HTTP calls in one request
            for sym in dict.fromkeys(syms):
                try:
                    data = pc.get_option_contract_snapshot(underlying, sym)
                    row = data.get("results") or data.get("result") or data
                    q = option_quote_from_snapshot_row(row)
                    out_map[sym] = q
                except PolygonNotFoundError:
                    partial = True
                except PolygonError:
                    partial = True

        quotes = [out_map[s] for s in inp.option_symbols if s in out_map]
        if partial:
            base_warnings.append("PARTIAL_DATA")
        if not quotes:
            base_warnings.append("NO_RESULTS")

        # cache deterministic payload only (quotes + base warnings)
        cache.set(
            key=key,
            tool=tool_name,
            asof=asof_norm,
            inputs_json=inputs_json,
            response_json=_stable_json_dumps(
                {
                    "quotes_by_symbol": {sym: _dump_model(q) for sym, q in out_map.items()},
                    "warnings": base_warnings,
                }
            ),
            ttl_seconds=CACHE_TTL_LATEST_SECONDS,
        )

        warnings = [*base_warnings, *req_warnings]
        return GetOptionQuotesOutput(
            meta=_meta(tool_name, inp.asof, warnings, primary_source="polygon"),
            quotes=quotes,
        )
    finally:
        pc.close()


def get_option_greeks(inp: GetOptionGreeksInput) -> GetOptionGreeksOutput:
    warnings: list[WarningCode] = []
    if inp.asof is not None:
        warnings.append("VENDOR_LIMIT")
    if inp.mode != "vendor_only":
        # vendor_then_bs fallback compute is Part 4/5
        warnings.append("VENDOR_LIMIT")

    by_underlying: dict[str, list[str]] = defaultdict(list)
    for sym in inp.option_symbols:
        by_underlying[_underlying_from_option_symbol(sym)].append(sym)

    pc = PolygonClient()
    try:
        out_map = {}
        partial = False

        for underlying, syms in by_underlying.items():
            for sym in syms:
                try:
                    data = pc.get_option_contract_snapshot(underlying, sym)
                    row = data.get("results") or data.get("result") or data
                    g = option_greeks_from_snapshot_row(row)
                    out_map[sym] = g
                except PolygonNotFoundError:
                    partial = True
                except PolygonError:
                    partial = True

        greeks = [out_map[s] for s in inp.option_symbols if s in out_map]
        if partial or any(
            (g.delta, g.gamma, g.theta, g.vega, g.iv) == (None, None, None, None, None)
            for g in greeks
        ):
            warnings.append("PARTIAL_DATA")
        if not greeks:
            warnings.append("NO_RESULTS")

        return GetOptionGreeksOutput(
            meta=_meta("get_option_greeks", inp.asof, warnings),
            greeks=greeks,
        )
    finally:
        pc.close()
