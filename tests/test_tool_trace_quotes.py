from __future__ import annotations

import json

import pytest

from voli.run_trace import end_trace, start_trace
from voli.tool_schemas import GetOptionQuotesInput
from voli.tools import polygon_tools as pt


def test_quotes_trace_logs_polygon_then_cache(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("VOLI_CACHE_PATH", str(tmp_path / "cache.sqlite"))
    monkeypatch.setenv("VOLI_TRACE_DIR", str(tmp_path / "traces"))
    pt._get_cache.cache_clear()

    calls: list[tuple[str, str]] = []

    class FakePolygonClient:
        def get_option_contract_snapshot(self, underlying: str, sym: str) -> dict:
            calls.append((underlying, sym))
            ts_ns = 1700000000000000000
            return {
                "results": {
                    "details": {"ticker": sym},
                    "last_quote": {
                        "bid": 1.0,
                        "ask": 1.1,
                        "sip_timestamp": ts_ns,
                        "participant_timestamp": ts_ns,
                    },
                    "last_trade": {"price": 1.05, "sip_timestamp": ts_ns},
                    "last_updated": ts_ns,
                }
            }

        def close(self) -> None:
            return None

    monkeypatch.setattr(pt, "PolygonClient", FakePolygonClient)

    s1 = "O:NVDA251219C00100000"
    s2 = "O:NVDA251219P00100000"
    inp = GetOptionQuotesInput(option_symbols=[s1, s2, s1], asof=None)

    start_trace("trace_quotes")

    out1 = pt.get_option_quotes(inp)
    assert out1.meta.primary_source == "polygon"
    assert len(calls) == 2  # deduped vendor calls

    out2 = pt.get_option_quotes(inp)
    assert out2.meta.primary_source == "cache"
    assert len(calls) == 2

    end_trace()

    trace_file = tmp_path / "traces" / "trace_quotes.jsonl"
    assert trace_file.exists()

    events = [json.loads(line) for line in trace_file.read_text(encoding="utf-8").splitlines()]
    tool_calls = [
        e for e in events if e.get("event") == "tool_call" and e.get("tool") == "get_option_quotes"
    ]

    assert len(tool_calls) == 2
    assert tool_calls[0]["primary_source"] == "polygon"
    assert tool_calls[1]["primary_source"] == "cache"
    assert tool_calls[0]["cache_key"] == tool_calls[1]["cache_key"]
    assert tool_calls[0]["inputs_json"] == tool_calls[1]["inputs_json"]

    pt._get_cache().close()
    pt._get_cache.cache_clear()
