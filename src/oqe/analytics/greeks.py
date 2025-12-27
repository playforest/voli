"""Greek/IV access helpers.

The agent receives an OptionGreeks per option_symbol from tools.
This module provides deterministic selection and missing-data signaling.

v1 scope:
- lookup helpers for iv/delta/gamma/theta/vega
- ATM selection for a given expiry/right (using spot-based nearest strike)
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from .iv_metrics import (
    MetricResult,
    _as_date,
    normalize_right,
    select_atm_strike,
    select_contract_by_strike,
)


@dataclass(frozen=True)
class GreeksSnapshot:
    option_symbol: str
    expiry: date
    strike: float
    right: str
    iv: float | None
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    flags: tuple[str, ...] = ()


def get_greeks_value(greeks: object | None, field: str) -> MetricResult[float]:
    """Pull a float field from a greeks object with deterministic flags."""

    if greeks is None:
        return MetricResult(None, ("MISSING_GREEKS",))
    val = getattr(greeks, field, None)
    if val is None:
        return MetricResult(None, (f"MISSING_{field.upper()}",))
    return MetricResult(float(val), ())


def lookup_greeks(
    greeks_by_symbol: Mapping[str, object],
    option_symbol: str,
) -> MetricResult[object]:
    g = greeks_by_symbol.get(option_symbol)
    if g is None:
        return MetricResult(None, ("MISSING_GREEKS",))
    return MetricResult(g, ())


def atm_greeks_for_expiry(
    *,
    spot: float,
    contracts: Sequence[object],
    greeks_by_symbol: Mapping[str, object],
    expiry: date | datetime | str,
    right: str,
) -> MetricResult[GreeksSnapshot]:
    """Select the ATM contract for expiry/right and return its greeks.

    - ATM strike chosen from strike grid for that expiry/right.
    - If the greeks object is missing or individual fields are missing, we return None values
      plus flags.

    Assumes contract has attrs: expiry, strike, right, option_symbol (or symbol).
    """

    exp = _as_date(expiry)
    r = normalize_right(right)

    strikes = [
        float(c.strike)
        for c in contracts
        if _as_date(c.expiry) == exp and normalize_right(c.right) == r
    ]
    atm = select_atm_strike(spot, strikes)
    if atm.value is None:
        return MetricResult(None, atm.flags + ("ATM_STRIKE_MISSING",))

    c_res = select_contract_by_strike(contracts, strike=atm.value, right=r, expiry=exp)
    if c_res.value is None:
        return MetricResult(None, c_res.flags + ("ATM_CONTRACT_MISSING",))

    c = c_res.value
    sym = getattr(c, "option_symbol", None) or getattr(c, "symbol", None)
    if not sym:
        return MetricResult(None, ("MISSING_OPTION_SYMBOL",))

    g = greeks_by_symbol.get(sym)
    flags: list[str] = []
    if g is None:
        flags.append("MISSING_GREEKS")

    def _f(name: str) -> float | None:
        if g is None:
            return None
        v = getattr(g, name, None)
        if v is None:
            flags.append(f"MISSING_{name.upper()}")
            return None
        return float(v)

    snap = GreeksSnapshot(
        option_symbol=sym,
        expiry=exp,
        strike=float(c.strike),
        right=r,
        iv=_f("iv"),
        delta=_f("delta"),
        gamma=_f("gamma"),
        theta=_f("theta"),
        vega=_f("vega"),
        flags=tuple(flags),
    )

    return MetricResult(snap, tuple(flags))
