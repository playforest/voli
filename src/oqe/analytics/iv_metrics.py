# src/oqe/analytics/iv_metrics.py
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class MetricResult(Generic[T]):
    value: T | None
    flags: tuple[str, ...] = ()


def _as_date(d: date | datetime | str) -> date:
    if isinstance(d, date) and not isinstance(d, datetime):
        return d
    if isinstance(d, datetime):
        return d.date()
    return date.fromisoformat(str(d))


def normalize_right(right: str) -> str:
    r = right.strip().lower()
    if r in {"c", "call", "calls"}:
        return "call"
    if r in {"p", "put", "puts"}:
        return "put"
    return r


def mid_price(
    bid: float | None,
    ask: float | None,
    last: float | None = None,
) -> MetricResult[float]:
    """Deterministic mid price.

    Order:
    1) if bid & ask present, non-negative, and ask>=bid: mid=(bid+ask)/2
    2) else if last present and non-negative: last (MID_NOT_FROM_BIDASK + MID_FROM_LAST)
    3) else if bid present and non-negative: bid (MID_NOT_FROM_BIDASK + MID_FROM_BID_ONLY)
    4) else if ask present and non-negative: ask (MID_NOT_FROM_BIDASK + MID_FROM_ASK_ONLY)
    5) else: None (MID_MISSING + missing-field flags)

    Diagnostic flags accumulated from earlier checks
    (NEGATIVE_BID/NEGATIVE_ASK/INVALID_BID_ASK/NEGATIVE_LAST) are propagated.
    """
    flags: list[str] = []

    if bid is not None:
        bid = float(bid)
    if ask is not None:
        ask = float(ask)
    if last is not None:
        last = float(last)

    if bid is not None and ask is not None:
        if bid < 0:
            flags.append("NEGATIVE_BID")
        if ask < 0:
            flags.append("NEGATIVE_ASK")
        if bid >= 0 and ask >= 0 and ask >= bid:
            return MetricResult((bid + ask) / 2.0, tuple(flags))
        flags.append("INVALID_BID_ASK")

    if last is not None and last < 0:
        flags.append("NEGATIVE_LAST")

    if last is not None and last >= 0:
        return MetricResult(
            last,
            tuple(flags) + ("MID_NOT_FROM_BIDASK", "MID_FROM_LAST"),
        )

    if bid is not None and bid >= 0:
        return MetricResult(
            bid,
            tuple(flags) + ("MID_NOT_FROM_BIDASK", "MID_FROM_BID_ONLY"),
        )

    if ask is not None and ask >= 0:
        return MetricResult(
            ask,
            tuple(flags) + ("MID_NOT_FROM_BIDASK", "MID_FROM_ASK_ONLY"),
        )

    missing: list[str] = []
    if bid is None:
        missing.append("MISSING_BID")
    if ask is None:
        missing.append("MISSING_ASK")
    if last is None:
        missing.append("MISSING_LAST")

    return MetricResult(None, tuple(flags) + tuple(missing) + ("MID_MISSING",))


def relative_spread(bid: float | None, ask: float | None) -> MetricResult[float]:
    """Compute (ask-bid)/mid using mid=(bid+ask)/2.

    Returns None if bid/ask invalid or mid==0.
    """
    if bid is None:
        return MetricResult(None, ("MISSING_BID",))
    if ask is None:
        return MetricResult(None, ("MISSING_ASK",))

    b = float(bid)
    a = float(ask)
    if b < 0 or a < 0:
        return MetricResult(None, ("NEGATIVE_BID_ASK",))
    if a < b:
        return MetricResult(None, ("ASK_LT_BID",))

    mid = (a + b) / 2.0
    if mid == 0:
        return MetricResult(None, ("ZERO_MID",))

    return MetricResult((a - b) / mid, ())


def is_spread_too_wide(
    bid: float | None,
    ask: float | None,
    *,
    max_relative_spread: float = 0.20,
) -> MetricResult[bool]:
    """True if relative spread exceeds threshold.

    If spread can't be computed, returns None + flags.
    """
    rs = relative_spread(bid, ask)
    if rs.value is None:
        return MetricResult(None, rs.flags)
    return MetricResult(rs.value > max_relative_spread, ())


def mid_from_quote(quote: object) -> MetricResult[float]:
    bid = getattr(quote, "bid", None)
    ask = getattr(quote, "ask", None)
    last = getattr(quote, "last", None)
    return mid_price(bid, ask, last)


def is_quote_spread_too_wide(
    quote: object,
    *,
    max_relative_spread: float = 0.20,
) -> MetricResult[bool]:
    bid = getattr(quote, "bid", None)
    ask = getattr(quote, "ask", None)
    return is_spread_too_wide(bid, ask, max_relative_spread=max_relative_spread)


def select_atm_strike(spot: float, strikes: Sequence[float]) -> MetricResult[float]:
    """Select nearest strike to spot with deterministic tie-break.

    Tie-break: lower strike if equidistant.
    """
    if spot is None:
        return MetricResult(None, ("MISSING_SPOT",))
    if not strikes:
        return MetricResult(None, ("NO_STRIKES",))

    s = float(spot)
    uniq = sorted({float(x) for x in strikes})
    best = min(uniq, key=lambda k: (abs(k - s), k))
    return MetricResult(best, ())


def select_contract_by_strike(
    contracts: Sequence[object],
    *,
    strike: float,
    right: str,
    expiry: date,
) -> MetricResult[object]:
    """Select a contract for expiry/right/strike deterministically.

    If multiple match, tie-break by option symbol lexicographically.
    """
    r = normalize_right(right)
    exp = _as_date(expiry)

    matches: list[object] = []
    for c in contracts:
        if _as_date(c.expiry) != exp:
            continue
        if normalize_right(c.right) != r:
            continue
        if float(c.strike) != float(strike):
            continue
        matches.append(c)

    if not matches:
        return MetricResult(None, ("NO_MATCHING_CONTRACT",))

    def _sym(c: object) -> str:
        return str(getattr(c, "option_symbol", None) or getattr(c, "symbol", None) or "")

    best = sorted(matches, key=_sym)[0]
    if not _sym(best):
        return MetricResult(None, ("MISSING_OPTION_SYMBOL",))
    return MetricResult(best, ())


@dataclass(frozen=True)
class TermStructureResult:
    atm_strike: float | None
    front_expiry: date | None
    next_expiry: date | None
    front_iv: float | None
    next_iv: float | None
    flags: tuple[str, ...] = ()


def _select_front_and_next_expiry(
    contracts: Sequence[object],
    right: str,
) -> MetricResult[tuple[date, date]]:
    r = normalize_right(right)
    expiries = sorted({_as_date(c.expiry) for c in contracts if normalize_right(c.right) == r})
    if len(expiries) < 2:
        return MetricResult(None, ("INSUFFICIENT_EXPIRIES",))
    return MetricResult((expiries[0], expiries[1]), ())


def atm_iv_term_structure(
    *,
    spot: float,
    contracts: Sequence[object],
    greeks_by_symbol: Mapping[str, object],
    right: str,
    quotes_by_symbol: Mapping[str, object] | None = None,
    max_relative_spread: float | None = None,
    exclude_if_spread_unknown: bool = True,
) -> TermStructureResult:
    """Compare front vs next expiry ATM IV (same strike).

    v1 moneyness rule: same strike (ATM strike selected from front expiry strike grid).

    Optional spread filtering:
    - If quotes_by_symbol and max_relative_spread are provided, we exclude contracts whose
      quote spread is too wide when building the strike grid AND when selecting IV points.
    - If spread can't be computed, exclude iff exclude_if_spread_unknown=True.

    Missing IV returns None and sets flags (e.g., MISSING_IV).
    """
    flags: list[str] = []

    exp_pair = _select_front_and_next_expiry(contracts, right)
    if exp_pair.value is None:
        return TermStructureResult(None, None, None, None, None, exp_pair.flags)

    front_expiry, next_expiry = exp_pair.value
    r = normalize_right(right)

    def _sym(c: object) -> str | None:
        return getattr(c, "option_symbol", None) or getattr(c, "symbol", None)

    def _include_by_spread(sym: str) -> bool:
        if quotes_by_symbol is None or max_relative_spread is None:
            return True

        q = quotes_by_symbol.get(sym)
        if q is None:
            flags.append("MISSING_QUOTE")
            return not exclude_if_spread_unknown

        tw = is_quote_spread_too_wide(q, max_relative_spread=max_relative_spread)
        if tw.value is None:
            flags.extend(list(tw.flags))
            flags.append("SPREAD_UNKNOWN")
            return not exclude_if_spread_unknown

        if tw.value:
            flags.append("FILTERED_WIDE_SPREAD")
            return False

        return True

    # Build strike grid for front expiry/right (optionally spread-filtered)
    strikes: list[float] = []
    for c in contracts:
        if _as_date(c.expiry) != front_expiry:
            continue
        if normalize_right(c.right) != r:
            continue
        sym = _sym(c)
        if not sym:
            flags.append("MISSING_OPTION_SYMBOL")
            continue
        if not _include_by_spread(str(sym)):
            continue
        strikes.append(float(c.strike))

    atm = select_atm_strike(spot, strikes)
    if atm.value is None:
        return TermStructureResult(
            None,
            front_expiry,
            next_expiry,
            None,
            None,
            tuple(flags + list(atm.flags)),
        )

    atm_strike = atm.value

    def _iv_for(exp: date) -> float | None:
        c_res = select_contract_by_strike(contracts, strike=atm_strike, right=r, expiry=exp)
        if c_res.value is None:
            flags.extend(list(c_res.flags))
            flags.append("MISSING_CONTRACT")
            return None

        sym = _sym(c_res.value)
        if not sym:
            flags.append("MISSING_OPTION_SYMBOL")
            return None

        if not _include_by_spread(str(sym)):
            flags.append("FILTERED_AT_POINT")
            return None

        g = greeks_by_symbol.get(str(sym))
        if g is None:
            flags.append("MISSING_GREEKS")
            return None

        iv = getattr(g, "iv", None)
        if iv is None:
            flags.append("MISSING_IV")
            return None

        return float(iv)

    front_iv = _iv_for(front_expiry)
    next_iv = _iv_for(next_expiry)

    dedup_flags = tuple(dict.fromkeys(tuple(flags)))
    return TermStructureResult(
        atm_strike, front_expiry, next_expiry, front_iv, next_iv, dedup_flags
    )
