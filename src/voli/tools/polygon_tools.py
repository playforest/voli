"""Cache + trace + envelope orchestration around the active DataProvider.

Despite the historical filename, this module is **provider-agnostic** as of
the DataProvider refactor: each tool resolves the active provider via
``voli.providers.get_active()`` and calls its ``fetch_*`` method. The vendor
I/O for Polygon now lives in ``voli.providers.polygon``; alternative providers
(yfinance, Tradier, ...) plug in via the same registry.

The filename is preserved so existing ``from voli.tools.polygon_tools import ...``
call sites (CLI, MCP server, agent executor, LLM tools) keep working without
churn. ``PolygonClient`` is also re-exported here for backwards compatibility
with tests that monkey-patch it at this path.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from voli.cache import SQLiteCache, default_cache_path, make_cache_key, ttl_for

# Backwards-compat re-export for tests that monkey-patch ``pt.PolygonClient``.
# Voli core no longer references it directly; the Polygon provider does.
from voli.polygon.client import PolygonClient  # noqa: F401
from voli.providers import get_active
from voli.run_trace import get_trace
from voli.tool_schemas import (
    GetOptionGreeksInput,
    GetOptionGreeksOutput,
    GetOptionQuotesInput,
    GetOptionQuotesOutput,
    GetTickerNewsInput,
    GetTickerNewsOutput,
    GetUnderlyingSnapshotInput,
    GetUnderlyingSnapshotOutput,
    ListOptionContractsInput,
    ListOptionContractsOutput,
    ToolMeta,
    WarningCode,
)

CACHE_TTL_LATEST_SECONDS = 30
CACHE_TTL_HISTORICAL_SECONDS = 24 * 60 * 60


def _dump_model(m, *, exclude: set[str] | None = None) -> dict:
    exclude = exclude or set()
    if hasattr(m, "model_dump"):  # pydantic v2
        return m.model_dump(mode="json", exclude_none=True, exclude=exclude)
    return json.loads(m.json(exclude_none=True, exclude=exclude))


def _meta(
    tool: str,
    asof: datetime | None,
    warnings: list[WarningCode],
    *,
    primary_source: str,
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
    return SQLiteCache(default_cache_path())


def _stable_json_dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _trace_tool_call(
    *,
    tool: str,
    inputs_json: str,
    cache_key: str,
    primary_source: str,
    warnings: list[WarningCode],
    asof_norm: str,
) -> None:
    t = get_trace()
    if t is None:
        return
    t.log(
        {
            "event": "tool_call",
            "tool": tool,
            "inputs_json": inputs_json,
            "cache_key": cache_key,
            "primary_source": primary_source,
            "warnings": list(warnings),
            "asof_norm": asof_norm,
        }
    )


# ----------------------------------------------------------------------------
# Tool entrypoints — orchestration only; vendor I/O lives in the active
# provider (default: voli.providers.polygon.PolygonProvider).
# ----------------------------------------------------------------------------


def get_underlying_snapshot(inp: GetUnderlyingSnapshotInput) -> GetUnderlyingSnapshotOutput:
    req_warnings: list[WarningCode] = []
    if inp.asof is not None:
        req_warnings.append("VENDOR_LIMIT")

    tool_name = "get_underlying_snapshot"
    effective_asof = None  # this endpoint is latest-only

    tool_inputs = _dump_model(inp, exclude={"asof"})
    key, asof_norm, inputs_json = make_cache_key(tool_name, tool_inputs, asof=effective_asof)

    cache = _get_cache()

    rec = cache.get(key)
    if rec is not None:
        cached = json.loads(rec.response_json)
        snapshot = cached["snapshot"]
        base_warnings: list[WarningCode] = cached.get("warnings", [])
        warnings = [*base_warnings, *req_warnings]

        _trace_tool_call(
            tool=tool_name,
            inputs_json=inputs_json,
            cache_key=key,
            primary_source="cache",
            warnings=warnings,
            asof_norm=asof_norm,
        )

        return GetUnderlyingSnapshotOutput(
            meta=_meta(tool_name, inp.asof, warnings, primary_source="cache"),
            snapshot=snapshot,
        )

    provider = get_active()
    snapshot, base_warnings = provider.fetch_underlying_snapshot(inp.ticker, asof=inp.asof)

    cache.set(
        key=key,
        tool=tool_name,
        asof=asof_norm,
        inputs_json=inputs_json,
        response_json=_stable_json_dumps({"snapshot": snapshot, "warnings": base_warnings}),
        ttl_seconds=ttl_for(tool_name, asof_is_latest=True),
    )

    warnings = [*base_warnings, *req_warnings]
    _trace_tool_call(
        tool=tool_name,
        inputs_json=inputs_json,
        cache_key=key,
        primary_source=provider.name,
        warnings=warnings,
        asof_norm=asof_norm,
    )

    return GetUnderlyingSnapshotOutput(
        meta=_meta(tool_name, inp.asof, warnings, primary_source=provider.name),
        snapshot=snapshot,
    )


def list_option_contracts(inp: ListOptionContractsInput) -> ListOptionContractsOutput:
    provider = get_active()
    contracts, warnings = provider.fetch_option_contracts(
        inp.ticker,
        right=inp.right,
        expiry=inp.expiry,
        strike_min=inp.strike_min,
        strike_max=inp.strike_max,
        limit=inp.limit,
    )
    return ListOptionContractsOutput(
        meta=_meta("list_option_contracts", None, list(warnings), primary_source=provider.name),
        contracts=contracts,
    )


def get_option_quotes(inp: GetOptionQuotesInput) -> GetOptionQuotesOutput:
    req_warnings: list[WarningCode] = []
    if inp.asof is not None:
        req_warnings.append("VENDOR_LIMIT")

    tool_name = "get_option_quotes"
    effective_asof = None  # snapshot endpoint is latest-only

    tool_inputs = _dump_model(inp, exclude={"asof"})
    key, asof_norm, inputs_json = make_cache_key(tool_name, tool_inputs, asof=effective_asof)

    cache = _get_cache()

    rec = cache.get(key)
    if rec is not None:
        cached = json.loads(rec.response_json)
        base_warnings: list[WarningCode] = cached.get("warnings", [])
        warnings = [*base_warnings, *req_warnings]
        qb = cached.get("quotes_by_symbol", {})
        quotes = [qb[s] for s in inp.option_symbols if s in qb]

        _trace_tool_call(
            tool=tool_name,
            inputs_json=inputs_json,
            cache_key=key,
            primary_source="cache",
            warnings=warnings,
            asof_norm=asof_norm,
        )

        return GetOptionQuotesOutput(
            meta=_meta(tool_name, inp.asof, warnings, primary_source="cache"),
            quotes=quotes,
        )

    provider = get_active()
    out_map, base_warnings = provider.fetch_option_quotes(list(inp.option_symbols), asof=inp.asof)
    quotes = [out_map[s] for s in inp.option_symbols if s in out_map]

    cache.set(
        key=key,
        tool=tool_name,
        asof=asof_norm,
        inputs_json=inputs_json,
        response_json=_stable_json_dumps(
            {
                "quotes_by_symbol": {sym: _dump_model(q) for sym, q in out_map.items()},
                "warnings": list(base_warnings),
            }
        ),
        ttl_seconds=ttl_for(tool_name, asof_is_latest=True),
    )

    warnings = [*base_warnings, *req_warnings]
    _trace_tool_call(
        tool=tool_name,
        inputs_json=inputs_json,
        cache_key=key,
        primary_source=provider.name,
        warnings=warnings,
        asof_norm=asof_norm,
    )

    return GetOptionQuotesOutput(
        meta=_meta(tool_name, inp.asof, warnings, primary_source=provider.name),
        quotes=quotes,
    )


def get_option_greeks(inp: GetOptionGreeksInput) -> GetOptionGreeksOutput:
    req_warnings: list[WarningCode] = []
    if inp.asof is not None:
        req_warnings.append("VENDOR_LIMIT")
    if inp.mode != "vendor_only":
        req_warnings.append("VENDOR_LIMIT")

    tool_name = "get_option_greeks"
    effective_asof = None

    tool_inputs = _dump_model(inp, exclude={"asof"})
    key, asof_norm, inputs_json = make_cache_key(tool_name, tool_inputs, asof=effective_asof)

    cache = _get_cache()

    rec = cache.get(key)
    if rec is not None:
        cached = json.loads(rec.response_json)
        base_warnings: list[WarningCode] = cached.get("warnings", [])
        warnings = [*base_warnings, *req_warnings]
        gb = cached.get("greeks_by_symbol", {})
        greeks = [gb[s] for s in inp.option_symbols if s in gb]

        _trace_tool_call(
            tool=tool_name,
            inputs_json=inputs_json,
            cache_key=key,
            primary_source="cache",
            warnings=warnings,
            asof_norm=asof_norm,
        )

        return GetOptionGreeksOutput(
            meta=_meta(tool_name, inp.asof, warnings, primary_source="cache"),
            greeks=greeks,
        )

    provider = get_active()
    out_map, base_warnings = provider.fetch_option_greeks(
        list(inp.option_symbols), asof=inp.asof, mode=inp.mode
    )
    greeks = [out_map[s] for s in inp.option_symbols if s in out_map]

    cache.set(
        key=key,
        tool=tool_name,
        asof=asof_norm,
        inputs_json=inputs_json,
        response_json=_stable_json_dumps(
            {
                "greeks_by_symbol": {sym: _dump_model(g) for sym, g in out_map.items()},
                "warnings": list(base_warnings),
            }
        ),
        ttl_seconds=ttl_for(tool_name, asof_is_latest=True),
    )

    warnings = [*base_warnings, *req_warnings]
    _trace_tool_call(
        tool=tool_name,
        inputs_json=inputs_json,
        cache_key=key,
        primary_source=provider.name,
        warnings=warnings,
        asof_norm=asof_norm,
    )

    return GetOptionGreeksOutput(
        meta=_meta(tool_name, inp.asof, warnings, primary_source=provider.name),
        greeks=greeks,
    )


# ----------------------------------------------------------------------------
# Bulk chain fetcher
#
# Combines contracts + quotes + greeks in one round-trip so the analytics
# layer never has to issue per-symbol greeks calls (which would turn a 5s
# call into a 45s call on liquid names like INTC / SPY).
#
# Adapter authors can implement provider.fetch_option_chain_bulk for fast
# analytics paths; a None return falls back to per-symbol calls (slow but
# correct).
# ----------------------------------------------------------------------------


def get_option_chain_bulk(
    ticker: str,
    *,
    right: str | None = None,
    expiry: str | None = None,
    max_pages: int = 20,
) -> tuple[list, dict, dict, str]:
    """Fetch the full chain (contracts + quotes + greeks) in one paginated call.

    Returns ``(contracts, quotes_by_symbol, greeks_by_symbol, source)`` where
    ``source`` is ``"cache"`` if served from the SQLite TTL cache, otherwise
    the active provider's name (e.g. ``"polygon"``).
    """

    tool_name = "get_option_chain_bulk"
    inputs = {"ticker": ticker, "right": right, "expiry": expiry}
    key, asof_norm, inputs_json = make_cache_key(tool_name, inputs, asof=None)
    cache = _get_cache()

    rec = cache.get(key)
    if rec is not None:
        cached = json.loads(rec.response_json)
        from voli.models import OptionContract, OptionGreeks, OptionQuote

        contracts = [OptionContract(**c) for c in cached["contracts"]]
        quotes = {k: OptionQuote(**v) for k, v in cached["quotes"].items()}
        greeks = {k: OptionGreeks(**v) for k, v in cached["greeks"].items()}
        _trace_tool_call(
            tool=tool_name,
            inputs_json=inputs_json,
            cache_key=key,
            primary_source="cache",
            warnings=[],
            asof_norm=asof_norm,
        )
        return contracts, quotes, greeks, "cache"

    provider = get_active()
    bulk_fn = getattr(provider, "fetch_option_chain_bulk", None)
    if bulk_fn is None:
        # Fallback: per-symbol path (correct but slow on liquid chains).
        contracts_only, _ = provider.fetch_option_contracts(
            ticker, right=right, expiry=None, limit=5000
        )
        symbols = [c.option_symbol for c in contracts_only]
        quotes_map, _ = provider.fetch_option_quotes(symbols)
        greeks_map, _ = provider.fetch_option_greeks(symbols)
        contracts = contracts_only
        quotes_by_symbol = quotes_map
        greeks_by_symbol = greeks_map
    else:
        contracts, quotes_by_symbol, greeks_by_symbol = bulk_fn(
            ticker, right=right, expiry=expiry, max_pages=max_pages
        )

    cache.set(
        key=key,
        tool=tool_name,
        asof=asof_norm,
        inputs_json=inputs_json,
        response_json=_stable_json_dumps(
            {
                "contracts": [_dump_model(c) for c in contracts],
                "quotes": {k: _dump_model(v) for k, v in quotes_by_symbol.items()},
                "greeks": {k: _dump_model(v) for k, v in greeks_by_symbol.items()},
            }
        ),
        ttl_seconds=ttl_for("get_option_quotes", asof_is_latest=True),
    )

    _trace_tool_call(
        tool=tool_name,
        inputs_json=inputs_json,
        cache_key=key,
        primary_source=provider.name,
        warnings=[],
        asof_norm=asof_norm,
    )

    return contracts, quotes_by_symbol, greeks_by_symbol, provider.name


def get_ticker_news(inp: GetTickerNewsInput) -> GetTickerNewsOutput:
    """Fetch recent news articles tagged to ``inp.ticker``.

    Cached with the same SQLite-backed TTL as the other latest-only tools
    (5 min by default for news, vs. 30s for prices). Run-trace is logged
    on every call. Provider absence (a custom provider that doesn't ship a
    news endpoint) surfaces as a clean ``VENDOR_LIMIT`` warning with an
    empty list rather than a crash.
    """

    tool_name = "get_ticker_news"
    effective_asof = None

    tool_inputs = _dump_model(inp)
    key, asof_norm, inputs_json = make_cache_key(tool_name, tool_inputs, asof=effective_asof)

    cache = _get_cache()

    rec = cache.get(key)
    if rec is not None:
        cached = json.loads(rec.response_json)
        news = cached.get("news", [])
        warnings: list[WarningCode] = cached.get("warnings", [])

        _trace_tool_call(
            tool=tool_name,
            inputs_json=inputs_json,
            cache_key=key,
            primary_source="cache",
            warnings=warnings,
            asof_norm=asof_norm,
        )

        return GetTickerNewsOutput(
            meta=_meta(tool_name, None, warnings, primary_source="cache"),
            news=news,
        )

    provider = get_active()

    try:
        items, base_warnings = provider.fetch_news(inp.ticker, limit=inp.limit)
    except NotImplementedError:
        # Custom provider didn't implement news. Surface that cleanly to the
        # caller rather than crashing the LLM mid-tool-call.
        warnings = ["VENDOR_LIMIT"]
        _trace_tool_call(
            tool=tool_name,
            inputs_json=inputs_json,
            cache_key=key,
            primary_source=provider.name,
            warnings=warnings,
            asof_norm=asof_norm,
        )
        return GetTickerNewsOutput(
            meta=_meta(tool_name, None, warnings, primary_source=provider.name),
            news=[],
        )

    cache.set(
        key=key,
        tool=tool_name,
        asof=asof_norm,
        inputs_json=inputs_json,
        response_json=_stable_json_dumps(
            {
                "news": [_dump_model(n) for n in items],
                "warnings": list(base_warnings),
            }
        ),
        ttl_seconds=ttl_for(tool_name, asof_is_latest=True),
    )

    _trace_tool_call(
        tool=tool_name,
        inputs_json=inputs_json,
        cache_key=key,
        primary_source=provider.name,
        warnings=base_warnings,
        asof_norm=asof_norm,
    )

    return GetTickerNewsOutput(
        meta=_meta(tool_name, None, list(base_warnings), primary_source=provider.name),
        news=items,
    )
