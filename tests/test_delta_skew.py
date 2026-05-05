from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from oqe.analytics.skew import delta_skew


@dataclass(frozen=True)
class _C:
    option_symbol: str
    expiry: date
    strike: float
    right: str


@dataclass(frozen=True)
class _G:
    iv: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None


@dataclass(frozen=True)
class _Q:
    bid: float | None
    ask: float | None
    last: float | None = None


def _chain_with_deltas():
    """Build a chain where delta values are explicitly set so we can target ±0.25 cleanly."""

    exp = date(2026, 1, 16)
    # Strikes paired with their (call_delta, put_delta) and IVs.
    # Calls: deltas drop from ~0.75 (deep ITM) to ~0.10 (OTM) as strike rises
    # Puts: deltas rise from ~-0.90 to ~-0.10 as strike rises (more negative for ITM puts)
    rows = [
        # (strike, call_delta, call_iv, put_delta, put_iv)
        (90.0, 0.80, 0.32, -0.20, 0.40),
        (95.0, 0.60, 0.30, -0.40, 0.36),
        (100.0, 0.50, 0.28, -0.50, 0.32),  # ATM
        (105.0, 0.25, 0.27, -0.75, 0.31),  # call leg target_delta=0.25
        (110.0, 0.10, 0.26, -0.90, 0.30),
    ]
    # We also want a put at delta ≈ -0.25 -> add an extra strike
    rows.append((92.5, 0.70, 0.31, -0.25, 0.38))  # put leg target_delta=-0.25

    contracts: list[_C] = []
    greeks: dict[str, _G] = {}
    for strike, cd, civ, pd_, piv in rows:
        for right, d, iv in [("call", cd, civ), ("put", pd_, piv)]:
            sym = f"O:{exp.isoformat()}:{right}:{strike:g}"
            contracts.append(_C(sym, exp, strike, right))
            greeks[sym] = _G(iv=iv, delta=d)
    return exp, contracts, greeks


def test_delta_skew_basic_25d():
    exp, contracts, greeks = _chain_with_deltas()
    # Expected: put_iv at delta -0.25 = 0.38 ; call_iv at delta 0.25 = 0.27
    # skew = 0.38 - 0.27 = 0.11
    res = delta_skew(
        contracts=contracts,
        greeks_by_symbol=greeks,
        expiry=exp,
        target_delta=0.25,
    )
    assert res.value is not None
    assert abs(res.value - 0.11) < 1e-9


def test_delta_skew_uses_absolute_target():
    # Negative target_delta should behave the same as its absolute value.
    exp, contracts, greeks = _chain_with_deltas()
    a = delta_skew(contracts=contracts, greeks_by_symbol=greeks, expiry=exp, target_delta=0.25)
    b = delta_skew(contracts=contracts, greeks_by_symbol=greeks, expiry=exp, target_delta=-0.25)
    assert a.value == b.value


def test_delta_skew_missing_call_leg_when_no_calls_for_expiry():
    exp = date(2026, 1, 16)
    # Only puts, no calls
    contracts = [_C("O:put:100", exp, 100.0, "put")]
    greeks = {"O:put:100": _G(iv=0.30, delta=-0.25)}

    res = delta_skew(contracts=contracts, greeks_by_symbol=greeks, expiry=exp, target_delta=0.25)
    assert res.value is None
    assert "MISSING_CALL_LEG" in res.flags


def test_delta_skew_skips_contracts_with_missing_delta():
    exp, contracts, greeks = _chain_with_deltas()
    # Strip delta from the call at 105 (the natural 25-delta target).
    sym = f"O:{exp.isoformat()}:call:105"
    g = greeks[sym]
    greeks[sym] = _G(iv=g.iv, delta=None)

    res = delta_skew(
        contracts=contracts,
        greeks_by_symbol=greeks,
        expiry=exp,
        target_delta=0.25,
    )
    # Without strike=105 as a candidate, the next-closest delta on the call side
    # is 0.10 (strike 110, distance 0.15) vs 0.50 (strike 100, distance 0.25).
    # So the call leg falls back to strike 110 with iv=0.26.
    # put_iv (delta -0.25) is still 0.38 -> skew = 0.38 - 0.26 = 0.12
    assert res.value is not None
    assert abs(res.value - 0.12) < 1e-9
    assert "MISSING_DELTA" in res.flags


def test_delta_skew_with_spread_filter_excludes_wide_quotes():
    exp, contracts, greeks = _chain_with_deltas()

    # Make the natural 25-delta call at strike 105 have a wide quote.
    quotes: dict[str, _Q] = {}
    for c in contracts:
        if c.option_symbol == f"O:{exp.isoformat()}:call:105":
            quotes[c.option_symbol] = _Q(bid=0.10, ask=10.0)  # huge rel spread
        else:
            quotes[c.option_symbol] = _Q(bid=1.0, ask=1.05)  # tight

    res = delta_skew(
        contracts=contracts,
        greeks_by_symbol=greeks,
        expiry=exp,
        target_delta=0.25,
        quotes_by_symbol=quotes,
        max_relative_spread=0.20,
    )
    # Filtered out the strike=105 call -> falls back to strike=110 (delta 0.10, iv 0.26).
    assert res.value is not None
    assert abs(res.value - (0.38 - 0.26)) < 1e-9
    assert "FILTERED_WIDE_SPREAD" in res.flags
