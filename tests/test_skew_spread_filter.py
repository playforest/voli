# tests/test_skew_spread_filter.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from oqe.analytics.skew import strike_iv_pairs


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


def test_strike_iv_pairs_filters_wide_spread():
    exp = date(2026, 1, 17)

    contracts = [
        C("A", exp, 95.0, "call"),
        C("B", exp, 100.0, "call"),
        C("C", exp, 105.0, "call"),
    ]

    greeks = {"A": G(iv=0.30), "B": G(iv=0.29), "C": G(iv=0.31)}

    # Make B very wide: mid=2, spread=4 => relative spread = 2.0 (too wide)
    quotes = {
        "A": Q(bid=1.0, ask=1.2),
        "B": Q(bid=0.0, ask=4.0),
        "C": Q(bid=2.0, ask=2.2),
    }

    out = strike_iv_pairs(
        contracts=contracts,
        greeks_by_symbol=greeks,
        expiry=exp,
        right="call",
        quotes_by_symbol=quotes,
        max_relative_spread=0.50,
    )

    assert out.value is not None
    strikes = [k for k, _iv in out.value.pairs]
    assert strikes == [95.0, 105.0]  # B filtered out
    assert "FILTERED_WIDE_SPREAD" in out.flags


def test_strike_iv_pairs_excludes_unknown_spread_by_default():
    exp = date(2026, 1, 17)

    contracts = [
        C("A", exp, 95.0, "call"),
        C("B", exp, 100.0, "call"),
    ]

    greeks = {"A": G(iv=0.30), "B": G(iv=0.29)}

    # Missing ask => spread unknown for B
    quotes = {
        "A": Q(bid=1.0, ask=1.1),
        "B": Q(bid=1.0, ask=None),
    }

    out = strike_iv_pairs(
        contracts=contracts,
        greeks_by_symbol=greeks,
        expiry=exp,
        right="call",
        quotes_by_symbol=quotes,
        max_relative_spread=0.50,
        exclude_if_spread_unknown=True,
    )

    assert out.value is not None
    strikes = [k for k, _iv in out.value.pairs]
    assert strikes == [95.0]
    assert "SPREAD_UNKNOWN" in out.flags
