from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from oqe.analytics.greeks import atm_greeks_for_expiry


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


def _chain():
    exp = date(2026, 1, 16)
    strikes = [95.0, 100.0, 105.0, 110.0]
    contracts: list[_C] = []
    greeks: dict[str, _G] = {}
    for k in strikes:
        for right in ("call", "put"):
            sym = f"O:{exp.isoformat()}:{right}:{k:g}"
            contracts.append(_C(sym, exp, k, right))
            greeks[sym] = _G(iv=0.30, delta=0.5, gamma=0.04, theta=-0.02, vega=0.10)
    return exp, contracts, greeks


def test_atm_greeks_happy_path():
    exp, contracts, greeks = _chain()

    res = atm_greeks_for_expiry(
        spot=102.0,
        contracts=contracts,
        greeks_by_symbol=greeks,
        expiry=exp,
        right="call",
    )
    assert res.value is not None
    snap = res.value
    assert snap.strike == 100.0
    assert snap.right == "call"
    assert snap.expiry == exp
    assert snap.iv == 0.30
    assert snap.delta == 0.5
    assert snap.gamma == 0.04
    assert snap.theta == -0.02
    assert snap.vega == 0.10
    assert res.flags == ()


def test_atm_greeks_missing_greeks_object():
    exp, contracts, greeks = _chain()
    atm_sym = f"O:{exp.isoformat()}:call:100"
    del greeks[atm_sym]

    res = atm_greeks_for_expiry(
        spot=102.0,
        contracts=contracts,
        greeks_by_symbol=greeks,
        expiry=exp,
        right="call",
    )
    assert res.value is not None  # snapshot still produced, fields are None
    snap = res.value
    assert snap.iv is None
    assert snap.delta is None
    assert "MISSING_GREEKS" in res.flags


def test_atm_greeks_missing_individual_field():
    exp, contracts, greeks = _chain()
    atm_sym = f"O:{exp.isoformat()}:call:100"
    greeks[atm_sym] = _G(iv=0.30, delta=None, gamma=0.04, theta=-0.02, vega=0.10)

    res = atm_greeks_for_expiry(
        spot=102.0,
        contracts=contracts,
        greeks_by_symbol=greeks,
        expiry=exp,
        right="call",
    )
    assert res.value is not None
    assert res.value.iv == 0.30
    assert res.value.delta is None
    assert "MISSING_DELTA" in res.flags


def test_atm_greeks_no_contracts_for_right():
    exp = date(2026, 1, 16)
    contracts = [_C(f"O:{exp.isoformat()}:call:100", exp, 100.0, "call")]
    greeks = {contracts[0].option_symbol: _G(iv=0.3, delta=0.5)}

    res = atm_greeks_for_expiry(
        spot=100.0,
        contracts=contracts,
        greeks_by_symbol=greeks,
        expiry=exp,
        right="put",
    )
    assert res.value is None
    assert "NO_STRIKES" in res.flags
    assert "ATM_STRIKE_MISSING" in res.flags


def test_atm_greeks_tie_break_higher():
    exp, contracts, greeks = _chain()

    # Spot exactly between 100 and 105 -> default "lower" picks 100, "higher" picks 105.
    lower = atm_greeks_for_expiry(
        spot=102.5,
        contracts=contracts,
        greeks_by_symbol=greeks,
        expiry=exp,
        right="call",
    )
    higher = atm_greeks_for_expiry(
        spot=102.5,
        contracts=contracts,
        greeks_by_symbol=greeks,
        expiry=exp,
        right="call",
        tie_break="higher",
    )
    assert lower.value is not None and lower.value.strike == 100.0
    assert higher.value is not None and higher.value.strike == 105.0
