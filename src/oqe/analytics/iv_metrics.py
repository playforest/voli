"""IV + pricing metrics.

v1 principles
- Deterministic: given the same inputs, always the same outputs.
- Conservative: when data is missing/invalid, return None + flags.
- Lightweight: no numpy dependency.

Notes
- "IV" here means the vendor-supplied/implied volatility field from OptionGreeks.
  We are not re-fitting vol from prices in v1.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class MetricResult(Generic[T]):
    """A deterministic value plus flags for partial/missing data."""

    value: T | None
    flags: tuple[str, ...] = ()

    def with_flag(self, flag: str) -> MetricResult[T]:
        if flag in self.flags:
            return self
        return MetricResult(self.value, self.flags + (flag,))


def _as_date(d: date | datetime | str) -> date:
    if isinstance(d, date) and not isinstance(d, datetime):
        return d
    if isinstance(d, datetime):
        return d.date()
    # Accept ISO strings ("YYYY-MM-DD" or full timestamp).
    try:
        return datetime.fromisoformat(d).date()
    except ValueError:
        return date.fromisoformat(d)


def normalize_right(right: str) -> str:
    """Normalize option right values.

    Accepts: 'call'/'put', 'c'/'p', 'C'/'P'.
    Returns: 'call' or 'put'.
    """

    r = (right or "").strip().lower()
    if r in {"c", "call"}:
        return "call"
    if r in {"p", "put"}:
        return "put"
    return r


# --- pricing helpers -------------------------------------------------------


def mid_price(
    bid: float | None, ask: float | None, last: float | None = None
) -> MetricResult[float]:
    """Compute a deterministic mid price.

    Rules (in order):
    1) If bid and ask are present, non-negative, and ask >= bid: mid = (bid + ask)/2.
    2) Else if last is present and non-negative: use last.
    3) Else if only bid is present and non-negative: use bid.
    4) Else if only ask is present and non-negative: use ask.
    5) Else: None.

    Flags are added when we fall back from the ideal case.
    """

    flags: list[str] = []

    def _ok(x: float | None) -> bool:
        return x is not None and x >= 0

    if _ok(bid) and _ok(ask) and ask >= bid:  # type: ignore[operator]
        return MetricResult((bid + ask) / 2, ())

    flags.append("MID_NOT_FROM_BIDASK")

    if _ok(last):
        return MetricResult(last, tuple(flags) + ("MID_FROM_LAST",))

    if _ok(bid) and ask is None:
        return MetricResult(bid, tuple(flags) + ("MID_FROM_BID_ONLY",))

    if _ok(ask) and bid is None:
        return MetricResult(ask, tuple(flags) + ("MID_FROM_ASK_ONLY",))

    # If both are present but invalid order or negatives, treat as missing.
    if bid is None:
        flags.append("MISSING_BID")
    if ask is None:
        flags.append("MISSING_ASK")
    if last is None:
        flags.append("MISSING_LAST")

    return MetricResult(None, tuple(flags) + ("MID_MISSING",))


def relative_spread(bid: float | None, ask: float | None) -> MetricResult[float]:
    """Relative spread = (ask - bid) / mid, where mid=(bid+ask)/2.

    Returns None if bid/ask missing or invalid.
    """

    if bid is None:
        return MetricResult(None, ("MISSING_BID", "SPREAD_MISSING"))
    if ask is None:
        return MetricResult(None, ("MISSING_ASK", "SPREAD_MISSING"))
    if bid < 0 or ask < 0:
        return MetricResult(None, ("NEGATIVE_QUOTE", "SPREAD_MISSING"))
    if ask < bid:
        return MetricResult(None, ("ASK_LT_BID", "SPREAD_MISSING"))

    mid = (bid + ask) / 2
    if mid == 0:
        return MetricResult(None, ("MID_ZERO", "SPREAD_MISSING"))

    return MetricResult((ask - bid) / mid, ())


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


# --- ATM selection ---------------------------------------------------------


def select_atm_strike(spot: float, strikes: Iterable[float]) -> MetricResult[float]:
    """Select nearest strike to spot (deterministic tie-break).

    Tie-break: if two strikes are equally distant, choose the *lower* strike.

    Returns None if strikes is empty.
    """

    strikes_list = list(strikes)
    if not strikes_list:
        return MetricResult(None, ("NO_STRIKES",))

    # Sort ensures deterministic tie-break.
    strikes_list.sort()

    best = strikes_list[0]
    best_dist = abs(best - spot)

    for k in strikes_list[1:]:
        dist = abs(k - spot)
        if dist < best_dist:
            best = k
            best_dist = dist
        elif dist == best_dist and k < best:
            best = k

    return MetricResult(best, ())


def select_contract_by_strike(
    contracts: Sequence[object],
    *,
    strike: float,
    right: str | None = None,
    expiry: date | datetime | str | None = None,
) -> MetricResult[object]:
    """Pick a single contract by strike + optional right/expiry.

    Assumes each contract has attributes: strike, right, expiry.
    Deterministic tie-break if multiple match: sort by option_symbol or symbol.
    """

    right_n = normalize_right(right) if right is not None else None
    expiry_d = _as_date(expiry) if expiry is not None else None

    matches: list[object] = []
    for c in contracts:
        if c.strike != strike:
            continue
        if right_n is not None and normalize_right(c.right) != right_n:
            continue
        if expiry_d is not None and _as_date(c.expiry) != expiry_d:
            continue
        matches.append(c)

    if not matches:
        flags = ["CONTRACT_NOT_FOUND"]
        if right_n is not None:
            flags.append("RIGHT_FILTERED")
        if expiry_d is not None:
            flags.append("EXPIRY_FILTERED")
        return MetricResult(None, tuple(flags))

    def _key(c: object) -> tuple[str, str]:
        # Polygon usually uses option_symbol, but we also support symbol.
        sym = getattr(c, "option_symbol", None) or getattr(c, "symbol", None) or ""
        r = normalize_right(getattr(c, "right", ""))
        return (sym, r)

    matches.sort(key=_key)
    return MetricResult(matches[0], ())


# --- term structure --------------------------------------------------------


@dataclass(frozen=True)
class TermStructureResult:
    atm_strike: float | None
    front_expiry: date | None
    next_expiry: date | None
    front_iv: float | None
    next_iv: float | None
    flags: tuple[str, ...] = ()


def atm_iv_term_structure(
    *,
    spot: float,
    contracts: Sequence[object],
    greeks_by_symbol: Mapping[str, object],
    right: str = "call",
) -> TermStructureResult:
    """Compare ATM IV for the two nearest expiries using the *same strike*.

    Strategy:
    - Find the two earliest expiries available for the given right.
    - Choose ATM strike using the *front* expiry strike grid.
    - Look up IV for that strike for front and next expiry.

    Assumes:
    - contract has attrs: expiry, strike, right, option_symbol (or symbol)
    - greeks object has attr: iv
    """

    right_n = normalize_right(right)

    # Collect expiries for this right.
    expiries = sorted(
        {_as_date(c.expiry) for c in contracts if normalize_right(c.right) == right_n}
    )
    if len(expiries) == 0:
        return TermStructureResult(None, None, None, None, None, ("NO_EXPIRIES",))
    if len(expiries) == 1:
        return TermStructureResult(None, expiries[0], None, None, None, ("ONLY_ONE_EXPIRY",))

    front, nxt = expiries[0], expiries[1]

    front_strikes = [
        c.strike
        for c in contracts
        if normalize_right(c.right) == right_n and _as_date(c.expiry) == front
    ]
    atm = select_atm_strike(spot, front_strikes)
    if atm.value is None:
        return TermStructureResult(None, front, nxt, None, None, atm.flags)

    strike = atm.value

    flags: list[str] = []

    def _iv_for(exp: date) -> float | None:
        c_res = select_contract_by_strike(contracts, strike=strike, right=right_n, expiry=exp)
        if c_res.value is None:
            flags.extend(c_res.flags)
            flags.append("MISSING_CONTRACT_FOR_IV")
            return None
        c = c_res.value
        sym = getattr(c, "option_symbol", None) or getattr(c, "symbol", None)
        if not sym:
            flags.append("MISSING_OPTION_SYMBOL")
            return None
        g = greeks_by_symbol.get(sym)
        if g is None:
            flags.append("MISSING_GREEKS")
            return None
        iv = getattr(g, "iv", None)
        if iv is None:
            flags.append("MISSING_IV")
            return None
        return float(iv)

    front_iv = _iv_for(front)
    next_iv = _iv_for(nxt)

    return TermStructureResult(strike, front, nxt, front_iv, next_iv, tuple(flags))
