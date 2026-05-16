from __future__ import annotations

from datetime import datetime
from typing import Any

from voli.models import NewsItem, OptionContract, OptionGreeks, OptionQuote

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


# Tolerance window for clamping near-zero negative greeks. Polygon has been
# observed returning gamma ~ -3e-10 and vega ~ -8e-5; both are noise from
# upstream Black-Scholes solvers. We pick 1e-3 - wide enough to absorb real
# vendor noise, narrow enough that a genuine negative greek (a real bug) still
# surfaces as a validation error.
_ZERO_NOISE_EPS = 1e-3


def _clamp_nonneg(v: Any) -> float | None:
    """Floor tiny negative floating-point noise from vendor greeks.

    Real gamma/vega can't be negative for vanilla options, but vendors emit
    near-zero noise that fails our `ge=0` model constraints. Clamp anything
    within `_ZERO_NOISE_EPS` of zero to exactly 0.0; pass real negatives
    through so they still raise (a real bug worth surfacing).
    """

    if v is None:
        return None
    f = float(v)
    if -_ZERO_NOISE_EPS <= f < 0.0:
        return 0.0
    return f


def option_greeks_from_snapshot_row(row: dict[str, Any]) -> OptionGreeks:
    d = row.get("details") or {}
    option_symbol = d["ticker"]

    g = row.get("greeks") or {}
    iv = row.get("implied_volatility")

    ts_ns = _best_ts_ns(row)

    return OptionGreeks(
        option_symbol=option_symbol,
        delta=g.get("delta"),
        gamma=_clamp_nonneg(g.get("gamma")),
        theta=g.get("theta"),
        vega=_clamp_nonneg(g.get("vega")),
        iv=float(iv) if iv is not None else None,
        ts=ns_to_utc_iso(ts_ns),
        source="polygon",
        model="vendor",
    )


def news_item_from_polygon_row(row: dict[str, Any]) -> NewsItem:
    """Normalise one row from Polygon's ``/v2/reference/news`` response.

    Polygon shape:
      {
        "id": "...",
        "publisher": {"name": "...", "homepage_url": "...", ...},
        "title": "...",
        "author": "...",
        "published_utc": "2024-01-15T13:30:00Z",
        "article_url": "https://...",
        "tickers": ["AAPL", "MSFT"],
        "description": "..."
      }
    """

    publisher = row.get("publisher") or {}
    publisher_name = publisher.get("name") or "unknown"

    published_raw = row["published_utc"]
    if isinstance(published_raw, str):
        # Polygon emits trailing "Z"; datetime.fromisoformat handles it in 3.11+
        published = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
    else:
        published = published_raw

    return NewsItem(
        id=str(row["id"]),
        published_utc=published,
        title=row["title"],
        article_url=row["article_url"],
        publisher=publisher_name,
        tickers=list(row.get("tickers") or []),
        description=row.get("description"),
        author=row.get("author"),
        source="polygon",
    )
