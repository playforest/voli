"""Regression tests for OptionQuote.mid auto-compute.

Pydantic >= 2.10 silently discards new model instances returned from a
``model_validator(mode="after")`` on frozen models. The earlier
implementation used that pattern and shipped a UserWarning + missing mid
under modern pydantic. This file pins the fixed ``mode="before"`` pattern.
"""

from __future__ import annotations

from datetime import UTC, datetime

from voli.models import OptionQuote


def _ts():
    return datetime(2026, 5, 5, 13, 9, 4, tzinfo=UTC)


def test_mid_auto_computed_from_bid_ask():
    q = OptionQuote(
        option_symbol="O:NVDA260516C00100000",
        bid=5.0,
        ask=5.2,
        ts=_ts(),
        source="polygon",
    )
    assert q.mid == 5.1


def test_explicit_mid_wins_over_auto_compute():
    q = OptionQuote(
        option_symbol="O:NVDA260516C00100000",
        bid=5.0,
        ask=5.2,
        mid=5.0,
        ts=_ts(),
        source="polygon",
    )
    assert q.mid == 5.0


def test_no_mid_when_only_bid_present():
    q = OptionQuote(
        option_symbol="O:NVDA260516C00100000",
        bid=5.0,
        ts=_ts(),
        source="polygon",
    )
    assert q.mid is None


def test_no_mid_when_only_ask_present():
    q = OptionQuote(
        option_symbol="O:NVDA260516C00100000",
        ask=5.2,
        ts=_ts(),
        source="polygon",
    )
    assert q.mid is None


def test_zero_bid_zero_ask_yields_zero_mid():
    # OTM strikes outside market hours often look like this on yfinance.
    # Mid of 0/0 should still compute (0.0), not stay None.
    q = OptionQuote(
        option_symbol="O:NVDA260516C00250000",
        bid=0.0,
        ask=0.0,
        ts=_ts(),
        source="yfinance",
    )
    assert q.mid == 0.0
