"""Stage B: analytics-tool tests.

The three analytics tools wrap `oqe.tools.polygon_tools.*` calls plus an
`oqe.analytics.*` computation. To test them deterministically we monkey-
patch the four polygon entrypoints with the synthetic registry's stubs.
That way the analytics tool's internal fetch sees the same NVDA=100,
SPY=500, IV=0.30/0.35 surface the eval harness uses, and we can assert
exact numeric outputs.
"""

from __future__ import annotations

import json

import pytest

from oqe.eval.synth_market import make_registry
from oqe.llm.analytics_tools import (
    _tool_compute_atm_iv_term_structure,
    _tool_compute_skew_slope,
    _tool_get_atm_greeks,
    build_analytics_tools,
)


@pytest.fixture()
def patched_polygon(monkeypatch):
    """Replace oqe.tools.polygon_tools.* with synthetic-market wrappers.

    The analytics tools fetch data through these four functions, so
    swapping them out covers every code path without touching Polygon.
    """

    reg = make_registry()
    underlying = reg.tools["get_underlying_snapshot"]
    list_contracts = reg.tools["list_option_contracts"]
    quotes = reg.tools["get_option_quotes"]
    greeks = reg.tools["get_option_greeks"]

    def _to_dict(model):
        # Pydantic input -> plain dict the synth registry expects.
        if hasattr(model, "model_dump"):
            return model.model_dump(mode="json", exclude_none=True)
        return dict(model)

    monkeypatch.setattr(
        "oqe.llm.analytics_tools.get_underlying_snapshot",
        lambda inp: underlying(_to_dict(inp)),
    )
    monkeypatch.setattr(
        "oqe.llm.analytics_tools.list_option_contracts",
        lambda inp: list_contracts(_to_dict(inp)),
    )
    monkeypatch.setattr(
        "oqe.llm.analytics_tools.get_option_quotes",
        lambda inp: quotes(_to_dict(inp)),
    )
    monkeypatch.setattr(
        "oqe.llm.analytics_tools.get_option_greeks",
        lambda inp: greeks(_to_dict(inp)),
    )
    return reg


# ---- compute_atm_iv_term_structure -----------------------------------------


def test_term_structure_call_side(patched_polygon) -> None:
    result = json.loads(_tool_compute_atm_iv_term_structure({"ticker": "NVDA"}))
    assert result["ticker"] == "NVDA"
    assert result["spot"] == 100.0
    assert result["right"] == "call"
    assert result["atm_strike"] == 100.0
    assert result["front_iv"] == pytest.approx(0.30, abs=1e-6)
    assert result["next_iv"] == pytest.approx(0.35, abs=1e-6)
    assert result["iv_diff"] == pytest.approx(0.05, abs=1e-6)
    assert result["front_expiry"] == "2026-05-09"
    assert result["next_expiry"] == "2026-05-16"


def test_term_structure_put_side(patched_polygon) -> None:
    result = json.loads(_tool_compute_atm_iv_term_structure({"ticker": "NVDA", "right": "put"}))
    assert result["right"] == "put"
    # Put-side base = call + 0.03.
    assert result["front_iv"] == pytest.approx(0.33, abs=1e-6)
    assert result["next_iv"] == pytest.approx(0.38, abs=1e-6)


def test_term_structure_missing_ticker_returns_error(patched_polygon) -> None:
    result = json.loads(_tool_compute_atm_iv_term_structure({}))
    assert result["error"] == "missing_ticker"


def test_term_structure_unknown_ticker_returns_no_contracts(patched_polygon) -> None:
    result = json.loads(_tool_compute_atm_iv_term_structure({"ticker": "ZZZZ"}))
    assert result["error"] == "no_contracts"


def test_term_structure_with_spread_filter(patched_polygon) -> None:
    """Synthetic quotes have bid=1.0 ask=2.0 (spread 66.7%); a 20% filter
    should drop everything and emit FILTERED_WIDE_SPREAD flags.
    """

    result = json.loads(
        _tool_compute_atm_iv_term_structure({"ticker": "NVDA", "max_relative_spread": 0.20})
    )
    assert result["max_relative_spread"] == 0.20
    # When everything's filtered, atm_strike can't be picked.
    assert result["atm_strike"] is None
    assert "FILTERED_WIDE_SPREAD" in result["flags"]


# ---- compute_skew_slope ----------------------------------------------------


def test_skew_slope_default_expiry(patched_polygon) -> None:
    """Symmetric V-shape smile (IV = 0.30 + 0.002 * |k - spot|) means the
    OLS slope across all strikes is exactly 0.
    """

    result = json.loads(_tool_compute_skew_slope({"ticker": "NVDA"}))
    assert result["ticker"] == "NVDA"
    assert result["right"] == "call"
    assert result["expiry"] == "2026-05-09"
    assert result["skew_slope"] == pytest.approx(0.0, abs=1e-9)


def test_skew_slope_explicit_expiry(patched_polygon) -> None:
    result = json.loads(_tool_compute_skew_slope({"ticker": "SPY", "expiry": "2026-05-16"}))
    assert result["expiry"] == "2026-05-16"
    assert result["skew_slope"] == pytest.approx(0.0, abs=1e-9)


def test_skew_slope_missing_ticker(patched_polygon) -> None:
    assert json.loads(_tool_compute_skew_slope({}))["error"] == "missing_ticker"


# ---- get_atm_greeks --------------------------------------------------------


def test_atm_greeks_default_expiry(patched_polygon) -> None:
    result = json.loads(_tool_get_atm_greeks({"ticker": "NVDA"}))
    assert result["ticker"] == "NVDA"
    assert result["spot"] == 100.0
    assert result["expiry"] == "2026-05-09"
    atm = result["atm"]
    assert atm["strike"] == 100.0
    assert atm["iv"] == pytest.approx(0.30, abs=1e-6)
    # Synthetic surface: delta=+0.5 for calls, gamma=0.02, theta=-0.10, vega=0.12.
    assert atm["delta"] == pytest.approx(0.5, abs=1e-9)
    assert atm["gamma"] == pytest.approx(0.02, abs=1e-9)
    assert atm["theta"] == pytest.approx(-0.10, abs=1e-9)
    assert atm["vega"] == pytest.approx(0.12, abs=1e-9)


def test_atm_greeks_put_side(patched_polygon) -> None:
    result = json.loads(_tool_get_atm_greeks({"ticker": "NVDA", "right": "put"}))
    atm = result["atm"]
    # Put-side: delta = -0.5 in the synthetic surface.
    assert atm["delta"] == pytest.approx(-0.5, abs=1e-9)
    assert atm["iv"] == pytest.approx(0.33, abs=1e-6)


def test_atm_greeks_explicit_expiry(patched_polygon) -> None:
    result = json.loads(_tool_get_atm_greeks({"ticker": "SPY", "expiry": "2026-05-16"}))
    assert result["expiry"] == "2026-05-16"
    assert result["atm"]["strike"] == 500.0
    assert result["atm"]["iv"] == pytest.approx(0.35, abs=1e-6)


def test_atm_greeks_missing_ticker(patched_polygon) -> None:
    assert json.loads(_tool_get_atm_greeks({}))["error"] == "missing_ticker"


# ---- ToolDef shape ---------------------------------------------------------


def test_build_analytics_tools_returns_three_tools() -> None:
    tools = build_analytics_tools()
    names = [t.name for t in tools]
    assert names == ["compute_atm_iv_term_structure", "compute_skew_slope", "get_atm_greeks"]
    for t in tools:
        assert isinstance(t.input_schema, dict)
        assert t.input_schema["type"] == "object"
        assert t.input_schema["required"] == ["ticker"]
