"""Cache-source visibility tests.

The marker shows up in three layers and each gets its own coverage:

1. ``get_option_chain_bulk`` (raw) returns "polygon" on a fresh fetch and
   "cache" on the second call within the TTL window.
2. The three analytics-tool wrappers surface the source through a flat
   ``primary_source`` field on their JSON payload.
3. The CLI's ``_extract_cache_marker`` helper handles both the nested
   (raw-tool) and flat (analytics) shapes plus malformed inputs.

If any of these break, the LLM's tool-call line goes back to being
opaque about whether the data was fresh.
"""

from __future__ import annotations

import json

import pytest

import voli.tools.polygon_tools as pt
from voli.cli import _extract_cache_marker
from voli.eval.synth_market import make_registry
from voli.llm.analytics_tools import (
    _tool_compute_atm_iv_term_structure,
    _tool_compute_skew_slope,
    _tool_get_atm_greeks,
)

# ---------------------------------------------------------------------------
# Layer 1: get_option_chain_bulk
# ---------------------------------------------------------------------------


class _FakeClient:
    """Just enough Polygon client to exercise the bulk path's cache hit/miss."""

    calls = 0

    def __init__(self, *a, **kw) -> None:
        pass

    def close(self) -> None:
        pass

    def list_option_chain_snapshot(self, ticker, q, extra_params=None):
        type(self).calls += 1
        row = {
            "details": {
                "contract_type": "call",
                "exercise_style": "american",
                "expiration_date": "2026-05-09",
                "shares_per_contract": 100,
                "strike_price": 100,
                "ticker": "O:NVDA260509C00100000",
            },
            "underlying_asset": {
                "ticker": "NVDA",
                "price": 100.0,
                "last_updated": 1766613596694930291,
                "timeframe": "REAL-TIME",
            },
            "implied_volatility": 0.30,
            "greeks": {"delta": 0.5, "gamma": 0.02, "theta": -0.10, "vega": 0.12},
        }
        return {"status": "OK"}, [row]


def test_bulk_fetch_reports_polygon_then_cache(monkeypatch, tmp_path) -> None:
    """First call goes to Polygon, second hits the in-process cache."""

    monkeypatch.setattr("voli.providers.polygon.PolygonClient", _FakeClient)
    _FakeClient.calls = 0

    # Force a fresh cache file so prior tests can't influence the source.
    cache_path = tmp_path / "bulk_marker.sqlite"
    monkeypatch.setenv("VOLI_CACHE_PATH", str(cache_path))
    pt._get_cache.cache_clear()

    _, _, _, src1 = pt.get_option_chain_bulk("NVDA")
    _, _, _, src2 = pt.get_option_chain_bulk("NVDA")

    assert src1 == "polygon"
    assert src2 == "cache"
    assert _FakeClient.calls == 1  # second call did NOT hit the network


# ---------------------------------------------------------------------------
# Layer 2: analytics-tool JSON carries primary_source
# ---------------------------------------------------------------------------


@pytest.fixture()
def patched_polygon(monkeypatch):
    reg = make_registry()
    underlying = reg.tools["get_underlying_snapshot"]
    list_contracts = reg.tools["list_option_contracts"]
    quotes = reg.tools["get_option_quotes"]
    greeks = reg.tools["get_option_greeks"]

    def _to_dict(model):
        if hasattr(model, "model_dump"):
            return model.model_dump(mode="json", exclude_none=True)
        return dict(model)

    monkeypatch.setattr(
        "voli.llm.analytics_tools.get_underlying_snapshot",
        lambda inp: underlying(_to_dict(inp)),
    )

    def _fake_bulk(ticker, *, right=None, expiry=None, max_pages=20):
        list_args: dict[str, object] = {"ticker": ticker, "limit": 500}
        if right is not None:
            list_args["right"] = right
        if expiry is not None:
            list_args["expiry"] = expiry
        contracts_resp = list_contracts(list_args)
        contracts = list(contracts_resp.contracts)
        if not contracts:
            return [], {}, {}, "polygon"
        symbols = [c.option_symbol for c in contracts]
        q_resp = quotes({"option_symbols": symbols})
        g_resp = greeks({"option_symbols": symbols})
        return (
            contracts,
            {q.option_symbol: q for q in q_resp.quotes},
            {g.option_symbol: g for g in g_resp.greeks},
            "polygon",
        )

    monkeypatch.setattr("voli.llm.analytics_tools.get_option_chain_bulk", _fake_bulk)
    return reg


def test_term_structure_emits_primary_source(patched_polygon) -> None:
    payload = json.loads(_tool_compute_atm_iv_term_structure({"ticker": "NVDA"}))
    assert payload["primary_source"] == "polygon"


def test_skew_slope_emits_primary_source(patched_polygon) -> None:
    payload = json.loads(_tool_compute_skew_slope({"ticker": "NVDA"}))
    assert payload["primary_source"] == "polygon"


def test_atm_greeks_emits_primary_source(patched_polygon) -> None:
    payload = json.loads(_tool_get_atm_greeks({"ticker": "NVDA"}))
    assert payload["primary_source"] == "polygon"


def test_no_contracts_error_still_carries_source(monkeypatch) -> None:
    """Even the error path should label whether the failed lookup hit the
    cache - useful when debugging a stale empty result.
    """

    def _empty_bulk(ticker, *, right=None, expiry=None, max_pages=20):
        return [], {}, {}, "cache"

    class _StubSnap:
        class meta:
            primary_source = "cache"

        class snapshot:
            spot = 100.0

    monkeypatch.setattr(
        "voli.llm.analytics_tools.get_underlying_snapshot",
        lambda inp: _StubSnap(),
    )
    monkeypatch.setattr("voli.llm.analytics_tools.get_option_chain_bulk", _empty_bulk)

    payload = json.loads(_tool_compute_atm_iv_term_structure({"ticker": "ZZZZ"}))
    assert payload["error"] == "no_contracts"
    assert payload["primary_source"] == "cache"


def test_mixed_source_when_snapshot_cached_chain_fresh(monkeypatch) -> None:
    """One side cached, the other live -> 'mixed', so the operator can
    tell that part of the answer just hit the network.
    """

    class _StubSnap:
        class meta:
            primary_source = "cache"

        class snapshot:
            spot = 100.0

    def _fresh_bulk(ticker, *, right=None, expiry=None, max_pages=20):
        return [], {}, {}, "polygon"

    monkeypatch.setattr(
        "voli.llm.analytics_tools.get_underlying_snapshot",
        lambda inp: _StubSnap(),
    )
    monkeypatch.setattr("voli.llm.analytics_tools.get_option_chain_bulk", _fresh_bulk)

    payload = json.loads(_tool_compute_atm_iv_term_structure({"ticker": "NVDA"}))
    assert payload["primary_source"] == "mixed"


# ---------------------------------------------------------------------------
# Layer 3: CLI helper
# ---------------------------------------------------------------------------


def test_extract_marker_reads_flat_field() -> None:
    assert _extract_cache_marker('{"primary_source": "cache", "x": 1}') == "cache"


def test_extract_marker_reads_nested_meta() -> None:
    payload = json.dumps({"meta": {"primary_source": "polygon", "tool": "x"}, "snapshot": {}})
    assert _extract_cache_marker(payload) == "polygon"


def test_extract_marker_returns_empty_for_non_json() -> None:
    assert _extract_cache_marker("not json at all") == ""


def test_extract_marker_returns_empty_for_missing_field() -> None:
    assert _extract_cache_marker('{"hello": "world"}') == ""


def test_extract_marker_returns_empty_for_non_dict_payload() -> None:
    """A JSON list/scalar shouldn't crash the renderer."""

    assert _extract_cache_marker("[1, 2, 3]") == ""
    assert _extract_cache_marker("42") == ""


def test_extract_marker_returns_empty_for_empty_string() -> None:
    assert _extract_cache_marker("") == ""
