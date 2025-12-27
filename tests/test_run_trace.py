from __future__ import annotations

import json

from oqe.run_trace import end_trace, start_trace


def test_run_trace_writes_jsonl(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OQE_TRACE_DIR", str(tmp_path))

    t = start_trace("test_trace")
    t.log({"event": "tool_call", "tool": "get_underlying_snapshot", "primary_source": "cache"})
    end_trace()

    p = tmp_path / "test_trace.jsonl"
    assert p.exists()

    lines = p.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 3  # start, tool_call, end

    obj = json.loads(lines[1])
    assert obj["trace_id"] == "test_trace"
    assert obj["event"] == "tool_call"
    assert obj["tool"] == "get_underlying_snapshot"
    assert obj["primary_source"] == "cache"
    assert "created_at" in obj
