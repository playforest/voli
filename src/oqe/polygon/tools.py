from __future__ import annotations

from typing import Any

from oqe.models import OptionContract, OptionGreeks, OptionQuote, UnderlyingSnapshot
from oqe.polygon.normalise import (
    option_contract_from_snapshot_row,
    option_greeks_from_snapshot_row,
    option_quote_from_snapshot_row,
)

from .client import OptionChainQuery, PolygonClient
from .helpers import ns_to_utc_iso


def get_underlying_snapshot_from_options(ticker: str) -> UnderlyingSnapshot:
    """
    Derive spot/asof from
    /v3/snapshot/options/{underlying} -> results[0].underlying_asset
    as I don't have polygon's stock snapshot entitlement
    """
    pc = PolygonClient()
    try:
        first, rows = pc.list_option_chain_snapshot(ticker, OptionChainQuery(limit=1, max_pages=1))
        if not rows:
            raise ValueError(f"No option snapshot results for {ticker}")

        ua = rows[0].get("underlying_asset") or {}
        spot = ua.get("price")
        last_updated_ns = ua.get("last_updated")
        _ua_timeframe = ua.get("timeframe")  # e.g. "DELAYED"

        if spot is None:
            raise ValueError(f"Missing underlying_asset.price for {ticker}")

        return UnderlyingSnapshot(
            ticker=ticker,
            spot=float(spot),
            ts=ns_to_utc_iso(int(last_updated_ns)) if last_updated_ns is not None else None,
            source="polygon",
        )
    finally:
        pc.close()


def list_option_contracts_from_options_snapshot(
    underlying: str,
    *,
    contract_type: str | None = None,  # "call" | "put"
    expiration_date: str | None = None,  # "YYYY-MM-DD"
    strike_price: float | None = None,
    limit: int = 250,
    max_pages: int = 10,
) -> list[OptionContract]:
    pc = PolygonClient()
    try:
        q = OptionChainQuery(
            contract_type=contract_type,
            expiration_date=expiration_date,
            strike_price=strike_price,
            limit=limit,
            max_pages=max_pages,
        )
        _first, rows = pc.list_option_chain_snapshot(underlying, q)

        return [option_contract_from_snapshot_row(r, fallback_underlying=underlying) for r in rows]
    finally:
        pc.close()


def _extract_single_row(snapshot_resp: dict[str, Any]) -> dict[str, Any]:
    # contract snapshot responses usually have "results" (dict), but i'll be defensive
    r = snapshot_resp.get("results") or snapshot_resp.get("result") or snapshot_resp
    if isinstance(r, list):
        return r[0]
    return r


def get_option_quotes_from_contract_snapshots(
    underlying: str,
    option_symbols: list[str],
) -> list[OptionQuote]:
    pc = PolygonClient()
    try:
        out: list[OptionQuote] = []
        for sym in option_symbols:
            data = pc.get_option_contract_snapshot(underlying, sym)
            row = _extract_single_row(data)
            out.append(option_quote_from_snapshot_row(row))
        return out
    finally:
        pc.close()


def get_option_greeks_from_contract_snapshots(
    underlying: str,
    option_symbols: list[str],
) -> list[OptionGreeks]:
    pc = PolygonClient()
    try:
        out: list[OptionGreeks] = []
        for sym in option_symbols:
            data = pc.get_option_contract_snapshot(underlying, sym)
            row = _extract_single_row(data)
            out.append(option_greeks_from_snapshot_row(row))
        return out
    finally:
        pc.close()
