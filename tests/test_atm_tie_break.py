from __future__ import annotations

import pytest

from voli.analytics.iv_metrics import select_atm_strike


def test_default_tie_break_picks_lower():
    res = select_atm_strike(spot=102.5, strikes=[100.0, 105.0])
    assert res.value == 100.0
    assert res.flags == ()


def test_tie_break_higher():
    res = select_atm_strike(spot=102.5, strikes=[100.0, 105.0], tie_break="higher")
    assert res.value == 105.0


def test_tie_break_invalid_value():
    res = select_atm_strike(spot=100.0, strikes=[95.0, 100.0], tie_break="middle")
    assert res.value is None
    assert "INVALID_TIE_BREAK" in res.flags


@pytest.mark.parametrize("tie_break", ["lower", "higher"])
def test_tie_break_irrelevant_when_unique_nearest(tie_break: str):
    # Spot=101, strikes 100 (dist 1) and 105 (dist 4) -> 100 regardless of tie-break
    res = select_atm_strike(spot=101.0, strikes=[100.0, 105.0], tie_break=tie_break)
    assert res.value == 100.0
