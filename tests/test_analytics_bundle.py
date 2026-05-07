# tests/test_analytics_bundle.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from voli.analytics.metrics_bundle import compute_v1_metrics_bundle


@dataclass(frozen=True)
class _C:
    option_symbol: str
    expiry: date
    strike: float
    right: str  # "call" / "put"


@dataclass(frozen=True)
class _G:
    iv: float | None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None


@pytest.fixture()
def synth_market():
    front = date(2026, 1, 17)
    next_ = date(2026, 2, 21)

    spot = 102.0
    strikes = [95, 100, 105, 110]

    contracts: list[_C] = []
    greeks_by_symbol: dict[str, _G] = {}

    # deterministic pattern:
    # - longer expiry higher IV
    # - puts have +0.03 offset vs calls
    # - small smile around 100
    for expiry, base in [(front, 0.30), (next_, 0.35)]:
        for k in strikes:
            for right in ["call", "put"]:
                sym = f"O:{expiry.isoformat()}:{right}:{k}"
                contracts.append(_C(sym, expiry, float(k), right))

                bump = 0.0
                if expiry == next_:
                    bump += 0.05
                if right == "put":
                    bump += 0.03
                bump += 0.002 * abs(k - 100)

                greeks_by_symbol[sym] = _G(iv=base + bump)

    return spot, contracts, greeks_by_symbol, front, next_


def test_compute_v1_metrics_bundle_smoke(synth_market):
    spot, contracts, greeks_by_symbol, front, _next = synth_market

    b = compute_v1_metrics_bundle(
        spot=spot,
        contracts=contracts,
        greeks_by_symbol=greeks_by_symbol,
        right="call",
    )

    assert b.term_structure.front_expiry == front
    assert b.term_structure.atm_strike == 100.0

    assert b.skew_slope.value is not None
    assert b.atm_greeks.value is not None
    assert b.atm_greeks.value.iv is not None
