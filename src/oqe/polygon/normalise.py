from __future__ import annotations

from typing import Any

from oqe.models import OptionContract, OptionGreeks, OptionQuote

from .helpers import ns_to_utc_iso


def option_contract_from_snapshot_row(
    row: dict[str, Any],
    *,
    fallback_underlying: str | None = None,
) -> OptionContract:
    d = row.get("details") or {}

    option_symbol = d["ticker"]
    expiry = d["expiration_date"]
    strike = float(d["strike_price"])

    ct = (d.get("contract_type") or "").lower()
    right = "C" if ct == "call" else "P" if ct == "put" else ct

    ua = row.get("underlying_asset") or {}
    underlying = ua.get("ticker") or fallback_underlying
    if not underlying:
        raise ValueError(
            "Missing underlying ticker (row.underlying_asset.ticker and fallback_underlying are both empty)"
        )

    multiplier = int(d.get("shares_per_contract", 100))

    exercise_style = d.get("exercise_style") or None
    if isinstance(exercise_style, str):
        exercise_style = exercise_style.lower()

    return OptionContract(
        option_symbol=option_symbol,
        underlying=underlying,
        expiry=expiry,
        strike=strike,
        right=right,
        multiplier=multiplier,
        exercise_style=exercise_style,
    )


def _best_ts_ns(row: dict[str, Any]) -> int | None:
    # Prefer quote timestamp, else trade timestamp, else underlying last_updated
    lq = row.get("last_quote") or {}
    if "sip_timestamp" in lq:
        return int(lq["sip_timestamp"])

    lt = row.get("last_trade") or {}
    if "sip_timestamp" in lt:
        return int(lt["sip_timestamp"])

    ua = row.get("underlying_asset") or {}
    if "last_updated" in ua:
        return int(ua["last_updated"])

    return None


def option_quote_from_snapshot_row(row: dict[str, Any]) -> OptionQuote:
    d = row.get("details") or {}
    option_symbol = d["ticker"]

    lq = row.get("last_quote") or {}
    lt = row.get("last_trade") or {}

    bid = lq.get("bid")
    ask = lq.get("ask")
    last = lt.get("price")

    mid = None
    if bid is not None and ask is not None:
        mid = (float(bid) + float(ask)) / 2.0

    ts_ns = _best_ts_ns(row)

    return OptionQuote(
        option_symbol=option_symbol,
        bid=float(bid) if bid is not None else None,
        ask=float(ask) if ask is not None else None,
        last=float(last) if last is not None else None,
        mid=float(mid) if mid is not None else None,
        ts=ns_to_utc_iso(ts_ns),
        source="polygon",
    )


def option_greeks_from_snapshot_row(row: dict[str, Any]) -> OptionGreeks:
    d = row.get("details") or {}
    option_symbol = d["ticker"]

    g = row.get("greeks") or {}
    iv = row.get("implied_volatility")

    ts_ns = _best_ts_ns(row)

    return OptionGreeks(
        option_symbol=option_symbol,
        delta=g.get("delta"),
        gamma=g.get("gamma"),
        theta=g.get("theta"),
        vega=g.get("vega"),
        iv=float(iv) if iv is not None else None,
        ts=ns_to_utc_iso(ts_ns),
        source="polygon",
        model="vendor",
    )
