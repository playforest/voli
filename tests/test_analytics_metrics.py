from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from voli.analytics.iv_metrics import (
    atm_iv_term_structure,
    is_quote_spread_too_wide,
    is_spread_too_wide,
    mid_from_quote,
    mid_price,
    relative_spread,
    select_atm_strike,
)
from voli.analytics.skew import skew_slope, strike_iv_pairs


@dataclass(frozen=True)
class DummyContract:
    option_symbol: str
    expiry: date
    strike: float
    right: str  # 'call' or 'put'


@dataclass(frozen=True)
class DummyGreeks:
    iv: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None


def _synthetic_chain():
    """Two expiries, small strike grid, deterministic IV patterns."""

    exp1 = date(2026, 1, 2)
    exp2 = date(2026, 1, 9)
    strikes = [90.0, 95.0, 100.0, 105.0, 110.0]

    contracts: list[DummyContract] = []
    greeks: dict[str, DummyGreeks] = {}

    # Pattern:
    # - Longer expiry has higher IV (+0.05)
    # - Puts have higher IV than calls (+0.02)
    # - Mild skew: lower strikes have slightly higher IV
    for exp, t_bonus in [(exp1, 0.00), (exp2, 0.05)]:
        for right, r_bonus in [("call", 0.00), ("put", 0.02)]:
            for k in strikes:
                sym = f"DUMMY_{exp.isoformat()}_{right}_{k:g}"
                contracts.append(
                    DummyContract(option_symbol=sym, expiry=exp, strike=k, right=right)
                )
                skew_bonus = (100.0 - k) * 0.001  # -0.01 ... +0.01 across grid
                base_iv = 0.30
                greeks[sym] = DummyGreeks(iv=base_iv + t_bonus + r_bonus + skew_bonus)

    return exp1, exp2, strikes, contracts, greeks


def test_atm_strike_selection_tie_break_lower_strike():
    # Spot exactly between 100 and 105 -> should choose 100 (lower strike tie-break)
    res = select_atm_strike(spot=102.5, strikes=[100.0, 105.0])
    assert res.value == 100.0


def test_mid_price_and_spread_logic():
    m = mid_price(1.0, 3.0)
    assert m.value == 2.0
    assert m.flags == ()

    rs = relative_spread(1.0, 3.0)
    assert rs.value == (3.0 - 1.0) / 2.0

    too_wide = is_spread_too_wide(1.0, 3.0, max_relative_spread=0.8)
    assert too_wide.value is True  # (2/2)=1.0 > 0.8

    # Missing bid -> no spread
    too_wide2 = is_spread_too_wide(None, 3.0)
    assert too_wide2.value is None
    assert "MISSING_BID" in too_wide2.flags


@dataclass(frozen=True)
class _Q:
    bid: float | None
    ask: float | None
    last: float | None = None


def test_quote_helpers_mid_and_spread():
    q = _Q(bid=1.0, ask=3.0, last=None)

    m = mid_from_quote(q)
    assert m.value == 2.0  # (1+3)/2

    tw = is_quote_spread_too_wide(q, max_relative_spread=0.8)
    assert tw.value is True  # rel spread = (3-1)/2 = 1.0 > 0.8

    q2 = _Q(bid=1.0, ask=None, last=None)
    tw2 = is_quote_spread_too_wide(q2)
    assert tw2.value is None
    assert "MISSING_ASK" in tw2.flags


def test_term_structure_atm_iv_comparison_calls():
    spot = 102.0
    exp1, exp2, _, contracts, greeks = _synthetic_chain()

    ts = atm_iv_term_structure(
        spot=spot, contracts=contracts, greeks_by_symbol=greeks, right="call"
    )
    assert ts.front_expiry == exp1
    assert ts.next_expiry == exp2
    assert ts.atm_strike == 100.0  # nearest to 102 is 100 (dist 2) vs 105 (dist 3)

    assert ts.front_iv is not None
    assert ts.next_iv is not None
    assert ts.next_iv > ts.front_iv  # longer expiry has higher IV


def test_skew_pairs_and_slope_puts():
    exp1, _, strikes, contracts, greeks = _synthetic_chain()

    curve_res = strike_iv_pairs(
        contracts=contracts, greeks_by_symbol=greeks, expiry=exp1, right="put"
    )
    assert curve_res.value is not None
    curve = curve_res.value

    assert len(curve.pairs) == len(strikes)
    assert [k for k, _ in curve.pairs] == sorted(strikes)

    slope_res = skew_slope(contracts=contracts, greeks_by_symbol=greeks, expiry=exp1, right="put")
    assert slope_res.value is not None
    # Our skew_bonus increases IV as strike decreases => IV decreases with strike => negative slope
    assert slope_res.value < 0


def test_missing_iv_is_flagged_and_skipped():
    exp1, _, _, contracts, greeks = _synthetic_chain()

    # Delete one IV point
    victim = next(
        c.option_symbol
        for c in contracts
        if c.expiry == exp1 and c.right == "call" and c.strike == 95.0
    )
    greeks[victim] = DummyGreeks(iv=None)

    curve_res = strike_iv_pairs(
        contracts=contracts, greeks_by_symbol=greeks, expiry=exp1, right="call"
    )
    assert curve_res.value is not None
    curve = curve_res.value

    # One point skipped
    assert len(curve.pairs) == 4
    assert "MISSING_IV" in curve.flags


def test_mid_price_fallback_is_deterministic():
    # No ask: uses bid
    m = mid_price(1.25, None, last=None)
    assert m.value == 1.25
    assert "MID_FROM_BID_ONLY" in m.flags

    # No bid/ask but last present: uses last
    m2 = mid_price(None, None, last=2.5)
    assert m2.value == 2.5
    assert "MID_FROM_LAST" in m2.flags
