"""Polygon.io data provider — Voli's bundled default.

Implements :class:`voli.providers.DataProvider` against Polygon's options
snapshot endpoints. Voli core (``voli.tools.polygon_tools``) handles caching,
run-trace logging, and meta envelope; this module owns the vendor I/O and
normalisation only.

Other adapters (yfinance, Tradier, ...) should mirror this structure.
"""

from __future__ import annotations

import contextlib
import re
from collections import defaultdict
from datetime import date, datetime

from voli.models import OptionContract, OptionGreeks, OptionQuote
from voli.polygon.client import OptionChainQuery, PolygonClient
from voli.polygon.helpers import ns_to_utc_iso
from voli.polygon.http import PolygonError, PolygonNotFoundError
from voli.polygon.normalise import (
    option_contract_from_snapshot_row,
    option_greeks_from_snapshot_row,
    option_quote_from_snapshot_row,
)

_OPTION_UNDERLYING_RE = re.compile(r"^O:([A-Z]+)\d{6}[CP]\d+")


def _underlying_from_option_symbol(sym: str) -> str:
    m = _OPTION_UNDERLYING_RE.match(sym.upper())
    if not m:
        raise ValueError(f"Cannot parse underlying from option_symbol: {sym}")
    return m.group(1)


class PolygonProvider:
    """Default data provider — fetches options data from Polygon.io.

    Reads ``POLYGON_API_KEY`` from the environment via :class:`PolygonClient`.
    """

    name: str = "polygon"

    # ---------------------------------------------------------------- snapshot
    def fetch_underlying_snapshot(
        self, ticker: str, *, asof: datetime | None = None
    ) -> tuple[dict, list[str]]:
        warnings: list[str] = []
        pc = PolygonClient()
        try:
            _first, rows = pc.list_option_chain_snapshot(
                ticker,
                OptionChainQuery(limit=1, max_pages=1),
            )
            if not rows:
                warnings.append("NO_RESULTS")
                raise PolygonNotFoundError(f"No option snapshot results for {ticker}")

            ua = rows[0].get("underlying_asset") or {}
            spot = ua.get("price")
            last_updated_ns = ua.get("last_updated")
            timeframe = ua.get("timeframe")

            if timeframe and str(timeframe).upper() != "REAL-TIME":
                warnings.append("STALE_DATA")

            if spot is None:
                warnings.append("PARTIAL_DATA")
                raise PolygonError(f"Missing underlying_asset.price for {ticker}")

            snapshot = {
                "ticker": ticker,
                "spot": float(spot),
                "ts": ns_to_utc_iso(int(last_updated_ns)) if last_updated_ns is not None else None,
                "source": self.name,
            }
            return snapshot, warnings
        finally:
            pc.close()

    # ---------------------------------------------------------------- contracts
    def fetch_option_contracts(
        self,
        ticker: str,
        *,
        right: str | None = None,
        expiry: date | None = None,
        strike_min: float | None = None,
        strike_max: float | None = None,
        limit: int = 500,
    ) -> tuple[list[OptionContract], list[str]]:
        warnings: list[str] = []

        contract_type = None
        if right == "C":
            contract_type = "call"
        elif right == "P":
            contract_type = "put"

        expiry_str = expiry.isoformat() if expiry is not None else None

        # Polygon snapshot pages are capped at 250.
        per_page = min(250, limit)
        max_pages = min(50, (limit // per_page) + 2)

        pc = PolygonClient()
        try:
            _first, rows = pc.list_option_chain_snapshot(
                ticker,
                OptionChainQuery(
                    contract_type=contract_type,
                    expiration_date=expiry_str,
                    limit=per_page,
                    max_pages=max_pages,
                ),
            )

            contracts = [
                option_contract_from_snapshot_row(r, fallback_underlying=ticker) for r in rows
            ]
            if strike_min is not None:
                contracts = [c for c in contracts if c.strike >= strike_min]
            if strike_max is not None:
                contracts = [c for c in contracts if c.strike <= strike_max]

            if not contracts:
                warnings.append("NO_RESULTS")

            if len(contracts) > limit:
                warnings.append("VENDOR_LIMIT")
                contracts = contracts[:limit]

            return contracts, warnings
        finally:
            pc.close()

    # ---------------------------------------------------------------- quotes
    def fetch_option_quotes(
        self,
        option_symbols: list[str],
        *,
        asof: datetime | None = None,
    ) -> tuple[dict[str, OptionQuote], list[str]]:
        warnings: list[str] = []

        by_underlying: dict[str, list[str]] = defaultdict(list)
        for sym in option_symbols:
            by_underlying[_underlying_from_option_symbol(sym)].append(sym)

        pc = PolygonClient()
        try:
            out_map: dict[str, OptionQuote] = {}
            partial = False

            for underlying, syms in by_underlying.items():
                # Dedupe: avoid duplicated HTTP for the same symbol in one request.
                for sym in dict.fromkeys(syms):
                    try:
                        data = pc.get_option_contract_snapshot(underlying, sym)
                        row = data.get("results") or data.get("result") or data
                        out_map[sym] = option_quote_from_snapshot_row(row)
                    except PolygonNotFoundError:
                        partial = True
                    except PolygonError:
                        partial = True

            if partial:
                warnings.append("PARTIAL_DATA")
            if not out_map:
                warnings.append("NO_RESULTS")

            return out_map, warnings
        finally:
            pc.close()

    # ---------------------------------------------------------------- greeks
    def fetch_option_greeks(
        self,
        option_symbols: list[str],
        *,
        asof: datetime | None = None,
        mode: str = "vendor_only",
    ) -> tuple[dict[str, OptionGreeks], list[str]]:
        warnings: list[str] = []

        by_underlying: dict[str, list[str]] = defaultdict(list)
        for sym in option_symbols:
            by_underlying[_underlying_from_option_symbol(sym)].append(sym)

        pc = PolygonClient()
        try:
            out_map: dict[str, OptionGreeks] = {}
            partial = False

            for underlying, syms in by_underlying.items():
                for sym in dict.fromkeys(syms):
                    try:
                        data = pc.get_option_contract_snapshot(underlying, sym)
                        row = data.get("results") or data.get("result") or data
                        out_map[sym] = option_greeks_from_snapshot_row(row)
                    except PolygonNotFoundError:
                        partial = True
                    except PolygonError:
                        partial = True

            if partial or any(
                (g.delta, g.gamma, g.theta, g.vega, g.iv) == (None, None, None, None, None)
                for g in out_map.values()
            ):
                warnings.append("PARTIAL_DATA")
            if not out_map:
                warnings.append("NO_RESULTS")

            return out_map, warnings
        finally:
            pc.close()

    # ---------------------------------------------------------------- bulk chain
    def fetch_option_chain_bulk(
        self,
        ticker: str,
        *,
        right: str | None = None,
        expiry: str | None = None,
        max_pages: int = 20,
    ) -> tuple[list[OptionContract], dict[str, OptionQuote], dict[str, OptionGreeks]]:
        contract_type: str | None = None
        if right == "C":
            contract_type = "call"
        elif right == "P":
            contract_type = "put"

        pc = PolygonClient()
        try:
            _first, rows = pc.list_option_chain_snapshot(
                ticker,
                OptionChainQuery(
                    contract_type=contract_type,
                    expiration_date=expiry,
                    limit=250,
                    max_pages=max_pages,
                ),
            )

            contracts: list[OptionContract] = []
            quotes_by_symbol: dict[str, OptionQuote] = {}
            greeks_by_symbol: dict[str, OptionGreeks] = {}

            for row in rows:
                try:
                    c = option_contract_from_snapshot_row(row, fallback_underlying=ticker)
                except (KeyError, ValueError):
                    continue
                contracts.append(c)
                with contextlib.suppress(KeyError, ValueError, TypeError):
                    quotes_by_symbol[c.option_symbol] = option_quote_from_snapshot_row(row)
                with contextlib.suppress(KeyError, ValueError, TypeError):
                    greeks_by_symbol[c.option_symbol] = option_greeks_from_snapshot_row(row)

            return contracts, quotes_by_symbol, greeks_by_symbol
        finally:
            pc.close()
