"""Offline tests for the YFinanceProvider — yfinance.Ticker is mocked."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest
from voli_yfinance.provider import YFinanceProvider


def _mk_chain():
    """Return a stub of yfinance's OptionChain namedtuple."""

    calls = pd.DataFrame(
        [
            {
                "contractSymbol": "NVDA260516C00100000",
                "strike": 100.0,
                "lastPrice": 5.10,
                "bid": 5.00,
                "ask": 5.20,
                "lastTradeDate": pd.Timestamp("2026-05-05T15:00:00Z"),
                "impliedVolatility": 0.42,
                "currency": "USD",
            },
            {
                "contractSymbol": "NVDA260516C00120000",
                "strike": 120.0,
                "lastPrice": 1.20,
                "bid": 1.15,
                "ask": 1.25,
                "lastTradeDate": pd.Timestamp("2026-05-05T15:00:00Z"),
                "impliedVolatility": 0.38,
                "currency": "USD",
            },
        ]
    )
    puts = pd.DataFrame(
        [
            {
                "contractSymbol": "NVDA260516P00100000",
                "strike": 100.0,
                "lastPrice": 4.90,
                "bid": 4.80,
                "ask": 5.00,
                "lastTradeDate": pd.Timestamp("2026-05-05T15:00:00Z"),
                "impliedVolatility": 0.45,
                "currency": "USD",
            }
        ]
    )
    return SimpleNamespace(calls=calls, puts=puts)


class _FakeTicker:
    options = ("2026-05-16", "2026-05-23")
    fast_info = {"lastPrice": 99.99}

    def option_chain(self, expiry):
        return _mk_chain()

    def history(self, period="1d"):
        return pd.DataFrame()


@pytest.fixture
def patched_yf():
    with patch("voli_yfinance.provider.yf.Ticker", lambda *_a, **_k: _FakeTicker()):
        yield


def test_fetch_underlying_snapshot_returns_voli_shape(patched_yf):
    p = YFinanceProvider()
    snap, warnings = p.fetch_underlying_snapshot("NVDA")
    assert snap["ticker"] == "NVDA"
    assert snap["spot"] == pytest.approx(99.99)
    assert snap["source"] == "yfinance"
    assert warnings == []


def test_fetch_option_contracts_filters_and_prefixes(patched_yf):
    p = YFinanceProvider()
    contracts, _ = p.fetch_option_contracts("NVDA", expiry=date(2026, 5, 16), right="C", limit=10)
    assert len(contracts) == 2
    assert all(c.option_symbol.startswith("O:") for c in contracts)
    assert all(c.right == "C" for c in contracts)
    assert {c.strike for c in contracts} == {100.0, 120.0}


def test_fetch_option_quotes_returns_dict(patched_yf):
    p = YFinanceProvider()
    out, warnings = p.fetch_option_quotes(["O:NVDA260516C00100000"])
    assert "O:NVDA260516C00100000" in out
    q = out["O:NVDA260516C00100000"]
    assert q.bid == pytest.approx(5.00)
    assert q.ask == pytest.approx(5.20)
    assert q.mid == pytest.approx(5.10)
    assert q.source == "yfinance"
    # No partial data when every requested symbol resolves.
    assert "PARTIAL_DATA" not in warnings


def test_fetch_option_greeks_warns_partial_and_returns_iv(patched_yf):
    p = YFinanceProvider()
    out, warnings = p.fetch_option_greeks(["O:NVDA260516C00100000"])
    g = out["O:NVDA260516C00100000"]
    # yfinance only publishes IV — the rest must be None and the caller warned.
    assert g.iv == pytest.approx(0.42)
    assert g.delta is None
    assert g.gamma is None
    assert g.theta is None
    assert g.vega is None
    assert "PARTIAL_DATA" in warnings


def test_fetch_option_chain_bulk_yields_contracts_quotes_greeks(patched_yf):
    p = YFinanceProvider()
    contracts, quotes, greeks = p.fetch_option_chain_bulk("NVDA", expiry="2026-05-16")
    assert len(contracts) == 3  # 2 calls + 1 put from the stub
    assert {q.option_symbol for q in quotes.values()} == {
        "O:NVDA260516C00100000",
        "O:NVDA260516C00120000",
        "O:NVDA260516P00100000",
    }
    # Greeks dict has same keys; iv populated, others None.
    assert all(g.delta is None for g in greeks.values())
    assert greeks["O:NVDA260516C00100000"].iv == pytest.approx(0.42)


def test_provider_name_is_yfinance(patched_yf):
    assert YFinanceProvider().name == "yfinance"
