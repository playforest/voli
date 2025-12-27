from __future__ import annotations

import json

import pytest

from oqe.run_trace import end_trace, start_trace
from oqe.tool_schemas import GetOptionGreeksInput
from oqe.tools import polygon_tools as pt


def test_greeks_trace_logs_polygon_then_cache(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("OQE_CACHE_PATH", str(tmp_path / "cache.sqlite"))
    monkeypatch.setenv("OQE_TRACE_DIR", str(tmp_path / "traces"))
    pt._get_cache.cache_clear()

    calls: list[tuple[str, str]] = []

    class FakePolygonClient:
        def get_option_contract_snapshot(self, underlying: str, sym: str) -> dict:
            calls.append((underlying, sym))
            ts_ns = 1700000000000000000
            return {
                "results": {
                    "details": {"ticker": sym},
                    "last_updated": ts_ns,
                    "last_quote": {
                        "bid": 1.0,
                        "ask": 1.1,
                        "sip_timestamp": ts_ns,
                        "participant_timestamp": ts_ns,
                    },
                    "greeks": {"delta": 0.5, "gamma": 0.1, "theta": -0.02, "vega": 0.3},
                    "implied_volatility": 0.4,
                }
            }

        def close(self) -> None:
            return None

    monkeypatch.setattr(pt, "PolygonClient", FakePolygonClient)

    s1 = "O:NVDA251219C00100000"
    s2 = "O:NVDA251219P00100000"
    inp = GetOptionGreeksInput(option_symbols=[s1, s2, s1], asof=None, mode="vendor_only")

    start_trace("trace_greeks")

    out1 = pt.get_option_greeks(inp)
    assert out1.meta.primary_source == "polygon"
    assert len(calls) == 2

    out2 = pt.get_option_greeks(inp)
    assert out2.meta.primary_source == "cache"
    assert len(calls) == 2

    end_trace()

    trace_file = tmp_path / "traces" / "trace_greeks.jsonl"
    assert trace_file.exists()

    events = [json.loads(line) for line in trace_file.read_text(encoding="utf-8").splitlines()]
    tool_calls = [
        e for e in events if e.get("event") == "tool_call" and e.get("tool") == "get_option_greeks"
    ]

    assert len(tool_calls) == 2
    assert tool_calls[0]["primary_source"] == "polygon"
    assert tool_calls[1]["primary_source"] == "cache"
    assert tool_calls[0]["cache_key"] == tool_calls[1]["cache_key"]
    assert tool_calls[0]["inputs_json"] == tool_calls[1]["inputs_json"]

    pt._get_cache().close()
    pt._get_cache.cache_clear()
