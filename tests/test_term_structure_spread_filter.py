# tests/test_term_structure_spread_filter.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from voli.analytics.iv_metrics import atm_iv_term_structure


@dataclass(frozen=True)
class C:
    option_symbol: str
    expiry: date
    strike: float
    right: str


@dataclass(frozen=True)
class G:
    iv: float | None


@dataclass(frozen=True)
class Q:
    bid: float | None
    ask: float | None
    last: float | None = None


def test_term_structure_uses_spread_filtered_strike_grid():
    front = date(2026, 1, 17)
    next_ = date(2026, 2, 21)

    spot = 102.0

    # Make 100 strike wide on front expiry so ATM should move to 105
    contracts = [
        C("F95", front, 95.0, "call"),
        C("F100", front, 100.0, "call"),
        C("F105", front, 105.0, "call"),
        C("N95", next_, 95.0, "call"),
        C("N100", next_, 100.0, "call"),
        C("N105", next_, 105.0, "call"),
    ]

    greeks = {
        "F95": G(iv=0.30),
        "F100": G(iv=0.29),
        "F105": G(iv=0.31),
        "N95": G(iv=0.35),
        "N100": G(iv=0.34),
        "N105": G(iv=0.36),
    }

    quotes = {
        "F95": Q(bid=1.0, ask=1.1),
        "F100": Q(bid=0.0, ask=4.0),  # very wide
        "F105": Q(bid=2.0, ask=2.1),
        "N95": Q(bid=1.0, ask=1.1),
        "N100": Q(bid=1.0, ask=1.1),
        "N105": Q(bid=2.0, ask=2.1),
    }

    out = atm_iv_term_structure(
        spot=spot,
        contracts=contracts,
        greeks_by_symbol=greeks,
        right="call",
        quotes_by_symbol=quotes,
        max_relative_spread=0.50,
    )

    assert out.atm_strike == 105.0
    assert out.front_iv == 0.31
    assert out.next_iv == 0.36
    assert "FILTERED_WIDE_SPREAD" in out.flags


def test_term_structure_excludes_unknown_spread_by_default():
    front = date(2026, 1, 17)
    next_ = date(2026, 2, 21)

    spot = 100.0

    contracts = [
        C("F100", front, 100.0, "call"),
        C("F105", front, 105.0, "call"),
        C("N100", next_, 100.0, "call"),
        C("N105", next_, 105.0, "call"),
    ]

    greeks = {
        "F100": G(iv=0.30),
        "F105": G(iv=0.31),
        "N100": G(iv=0.35),
        "N105": G(iv=0.36),
    }

    quotes = {
        "F100": Q(bid=1.0, ask=None),  # unknown spread -> excluded by default
        "F105": Q(bid=1.0, ask=1.1),
        "N100": Q(bid=1.0, ask=1.1),
        "N105": Q(bid=1.0, ask=1.1),
    }

    out = atm_iv_term_structure(
        spot=spot,
        contracts=contracts,
        greeks_by_symbol=greeks,
        right="call",
        quotes_by_symbol=quotes,
        max_relative_spread=0.50,
        exclude_if_spread_unknown=True,
    )

    assert out.atm_strike == 105.0
    assert "SPREAD_UNKNOWN" in out.flags
