from __future__ import annotations

from oqe.models import UnderlyingSnapshot  # adjust import if your model lives elsewhere

from .client import OptionChainQuery, PolygonClient
from .normalise import ns_to_utc_iso


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
