# tests/test_analytics_bundle_spread_filter.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from voli.analytics.metrics_bundle import compute_v1_metrics_bundle


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


def test_bundle_applies_spread_filter_to_term_structure_and_skew():
    front = date(2026, 1, 17)
    next_ = date(2026, 2, 21)

    # spot between 100 and 105, normally ATM=100
    spot = 102.0

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

    # Make 100 strike wide on front expiry -> ATM should move to 105 in term structure
    quotes = {
        "F100": Q(bid=0.0, ask=4.0),  # huge relative spread
        "F105": Q(bid=2.0, ask=2.1),
        "N100": Q(bid=1.0, ask=1.1),
        "N105": Q(bid=2.0, ask=2.1),
    }

    b = compute_v1_metrics_bundle(
        spot=spot,
        contracts=contracts,
        greeks_by_symbol=greeks,
        right="call",
        quotes_by_symbol=quotes,
        max_relative_spread=0.50,
    )

    assert b.term_structure.atm_strike == 105.0
    assert b.term_structure.front_iv == 0.31
    assert b.term_structure.next_iv == 0.36
    assert "FILTERED_WIDE_SPREAD" in b.term_structure.flags
