from __future__ import annotations

from datetime import UTC

import oqe.tools.polygon_tools as pt
from oqe.polygon.http import PolygonNotFoundError
from oqe.tool_schemas import (
    GetOptionGreeksInput,
    GetOptionQuotesInput,
    GetUnderlyingSnapshotInput,
    ListOptionContractsInput,
)

# --- fixtures (raw Polygon-ish rows) ---

ROW_CALL_110 = {
    "details": {
        "contract_type": "call",
        "exercise_style": "american",
        "expiration_date": "2025-12-26",
        "shares_per_contract": 100,
        "strike_price": 110,
        "ticker": "O:AAPL251226C00110000",
    },
    "underlying_asset": {
        "last_updated": 1766613596694930291,
        "price": 273.43,
        "ticker": "AAPL",
        "timeframe": "DELAYED",
    },
    "last_trade": {
        "sip_timestamp": 1766591058341623991,
        "price": 164.17,
        "size": 1,
        "exchange": 308,
        "timeframe": "DELAYED",
    },
    "greeks": {
        "delta": 0.99,
        "gamma": 0.00017,
        "theta": -0.70,
        "vega": 0.0058,
    },
    "implied_volatility": 6.2,
}

ROW_CALL_120 = {
    "details": {
        "contract_type": "call",
        "exercise_style": "american",
        "expiration_date": "2025-12-26",
        "shares_per_contract": 100,
        "strike_price": 120,
        "ticker": "O:AAPL251226C00120000",
    },
    "underlying_asset": {"ticker": "AAPL"},
}

ROW_PUT_110 = {
    "details": {
        "contract_type": "put",
        "exercise_style": "american",
        "expiration_date": "2025-12-26",
        "shares_per_contract": 100,
        "strike_price": 110,
        "ticker": "O:AAPL251226P00110000",
    },
    "underlying_asset": {"ticker": "AAPL"},
}

ROW_EMPTY_GREEKS = {
    "details": {
        "contract_type": "call",
        "exercise_style": "american",
        "expiration_date": "2025-12-26",
        "shares_per_contract": 100,
        "strike_price": 110,
        "ticker": "O:AAPL251226C00110000",
    },
    "last_trade": {"sip_timestamp": 1766591058341623991, "price": 164.17},
    "greeks": {},  # -> all None
    "implied_volatility": None,
}


# --- Fake client to avoid network calls ---


class FakePolygonClient:
    def __init__(self, *args, **kwargs):
        pass

    def close(self) -> None:
        pass

    def list_option_chain_snapshot(self, underlying, q, extra_params=None):
        # Return rows for contracts listing + underlying snapshot derivation
        return {"status": "OK"}, [ROW_CALL_110, ROW_CALL_120, ROW_PUT_110]

    def get_option_contract_snapshot(self, underlying: str, option_contract: str):
        if option_contract == "O:AAPL251226C00110000":
            return {"results": ROW_CALL_110}
        if option_contract == "O:AAPL251226C00110000_EMPTYG":
            return {"results": ROW_EMPTY_GREEKS}
        raise PolygonNotFoundError("not found")


def _install_fake_client(monkeypatch):
    monkeypatch.setattr(pt, "PolygonClient", FakePolygonClient)


# --- tests ---


def test_get_underlying_snapshot(monkeypatch):
    _install_fake_client(monkeypatch)

    out = pt.get_underlying_snapshot(GetUnderlyingSnapshotInput(ticker="AAPL"))
    assert out.meta.tool == "get_underlying_snapshot"
    assert out.meta.primary_source == "polygon"
    assert out.snapshot.ticker == "AAPL"
    assert out.snapshot.spot == 273.43
    assert out.snapshot.ts.tzinfo is not None
    # because timeframe is DELAYED in fixture
    assert "STALE_DATA" in out.meta.warnings


def test_list_option_contracts_filters_and_limit(monkeypatch):
    _install_fake_client(monkeypatch)

    out = pt.list_option_contracts(
        ListOptionContractsInput(
            ticker="AAPL",
            expiry="2025-12-26",
            right="C",
            strike_min=115,
            limit=1,
        )
    )

    assert out.meta.tool == "list_option_contracts"
    assert len(out.contracts) == 1
    c0 = out.contracts[0]
    assert c0.underlying == "AAPL"
    assert c0.right == "C"
    assert c0.strike >= 115


def test_get_option_quotes_partial_data(monkeypatch):
    _install_fake_client(monkeypatch)

    out = pt.get_option_quotes(
        GetOptionQuotesInput(option_symbols=["O:AAPL251226C00110000", "O:AAPL251226C00999999"])
    )

    assert out.meta.tool == "get_option_quotes"
    assert "PARTIAL_DATA" in out.meta.warnings
    assert len(out.quotes) == 1
    q = out.quotes[0]
    assert q.option_symbol == "O:AAPL251226C00110000"
    assert q.last == 164.17
    assert q.ts.tzinfo is not None
    assert q.ts.astimezone(UTC).tzinfo == UTC


def test_get_option_greeks_partial_when_missing_values(monkeypatch):
    _install_fake_client(monkeypatch)

    out = pt.get_option_greeks(
        GetOptionGreeksInput(option_symbols=["O:AAPL251226C00110000_EMPTYG"])
    )

    assert out.meta.tool == "get_option_greeks"
    assert "PARTIAL_DATA" in out.meta.warnings
    assert len(out.greeks) == 1
    g = out.greeks[0]
    assert g.option_symbol == "O:AAPL251226C00110000"
    assert g.delta is None
    assert g.iv is None


def test_get_option_greeks_vendor_then_bs_warns_vendor_limit(monkeypatch):
    _install_fake_client(monkeypatch)

    out = pt.get_option_greeks(
        GetOptionGreeksInput(
            option_symbols=["O:AAPL251226C00110000"],
            mode="vendor_then_bs",
        )
    )
    assert "VENDOR_LIMIT" in out.meta.warnings
