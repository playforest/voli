from __future__ import annotations

import json

import pytest

from voli.run_trace import end_trace, start_trace
from voli.tool_schemas import GetUnderlyingSnapshotInput
from voli.tools import polygon_tools as pt


def test_underlying_trace_logs_polygon_then_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    # Isolate both cache + trace output
    monkeypatch.setenv("VOLI_CACHE_PATH", str(tmp_path / "cache.sqlite"))
    monkeypatch.setenv("VOLI_TRACE_DIR", str(tmp_path / "traces"))

    pt._get_cache.cache_clear()

    calls: list[tuple[str, object]] = []

    class FakePolygonClient:
        def list_option_chain_snapshot(self, ticker: str, query) -> tuple[dict, list[dict]]:
            calls.append((ticker, query))
            row = {
                "underlying_asset": {
                    "price": 123.45,
                    "last_updated": 1700000000000000000,
                    "timeframe": "REAL-TIME",
                }
            }
            return {}, [row]

        def close(self) -> None:
            return None

    monkeypatch.setattr(pt, "PolygonClient", FakePolygonClient)

    start_trace("trace_demo")

    # first call -> vendor
    out1 = pt.get_underlying_snapshot(GetUnderlyingSnapshotInput(ticker="NVDA", asof=None))
    assert out1.meta.primary_source == "polygon"
    assert len(calls) == 1

    # second call -> cache
    out2 = pt.get_underlying_snapshot(GetUnderlyingSnapshotInput(ticker="NVDA", asof=None))
    assert out2.meta.primary_source == "cache"
    assert len(calls) == 1

    end_trace()

    # Assert trace events
    trace_file = tmp_path / "traces" / "trace_demo.jsonl"
    assert trace_file.exists()

    events = [json.loads(line) for line in trace_file.read_text(encoding="utf-8").splitlines()]
    tool_calls = [
        e
        for e in events
        if e.get("event") == "tool_call" and e.get("tool") == "get_underlying_snapshot"
    ]

    assert len(tool_calls) == 2
    assert tool_calls[0]["primary_source"] == "polygon"
    assert tool_calls[1]["primary_source"] == "cache"
    assert tool_calls[0]["cache_key"] == tool_calls[1]["cache_key"]
    assert tool_calls[0]["inputs_json"] == tool_calls[1]["inputs_json"]

    pt._get_cache().close()
    pt._get_cache.cache_clear()
