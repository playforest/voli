"""Stage C: LLM replay companion tests.

We don't drive a real LLM in these tests - we drop a companion JSON into
the trace dir and verify the dump/load round trip plus the `voli replay`
re-render path. End-to-end through `voli llm-ask --trace` is exercised in
test_llm_e2e_replay below using a stub provider.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from voli.cli import main
from voli.llm import LLMProvider, StepComplete, TextDelta, ToolCallStart, ToolResult
from voli.llm.replay import (
    LLMRunRecord,
    companion_path,
    dump_llm_run,
    load_llm_run,
)


@pytest.fixture()
def trace_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("VOLI_TRACE_DIR", str(tmp_path))
    return tmp_path


# ---- dump_llm_run / load_llm_run ------------------------------------------


def test_round_trip(trace_dir: Path) -> None:
    path = dump_llm_run(
        "tc_001",
        prompt="hi",
        provider="anthropic",
        model="claude-x",
        answer="hello back",
        stop_reason="end_turn",
        tool_calls=[ToolCallStart(id="a", name="echo", arguments={"x": 1})],
        tool_results=[ToolResult(id="a", name="echo", content='{"echo": 1}')],
    )
    assert path == companion_path("tc_001")
    assert path.exists()

    loaded = load_llm_run("tc_001")
    assert isinstance(loaded, LLMRunRecord)
    assert loaded.prompt == "hi"
    assert loaded.provider == "anthropic"
    assert loaded.model == "claude-x"
    assert loaded.answer == "hello back"
    assert loaded.tool_calls[0]["name"] == "echo"
    assert loaded.tool_calls[0]["arguments"] == {"x": 1}


def test_resolve_by_id_or_full_path(trace_dir: Path) -> None:
    dump_llm_run(
        "tc_path",
        prompt="x",
        provider="openai",
        model="gpt-x",
        answer="y",
        stop_reason="end_turn",
        tool_calls=[],
        tool_results=[],
    )
    by_id = load_llm_run("tc_path")
    by_path = load_llm_run(str(companion_path("tc_path")))
    assert by_id.prompt == by_path.prompt


def test_missing_target_raises(trace_dir: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_llm_run("does_not_exist")


# ---- voli replay auto-detects LLM companion --------------------------------


def test_voli_replay_renders_llm_companion(trace_dir: Path) -> None:
    dump_llm_run(
        "tc_replay",
        prompt="What is NVDA spot?",
        provider="anthropic",
        model="claude-test",
        answer="NVDA is around $200.",
        stop_reason="end_turn",
        tool_calls=[
            ToolCallStart(id="a", name="get_underlying_snapshot", arguments={"ticker": "NVDA"})
        ],
        tool_results=[
            ToolResult(
                id="a",
                name="get_underlying_snapshot",
                content='{"snapshot": {"ticker": "NVDA", "spot": 200, '
                '"ts": "2026-05-06T00:00:00Z", "source": "polygon"}}',
            )
        ],
    )

    out = io.StringIO()
    rc = main(["replay", "--no-color", "tc_replay"], out=out)
    text = out.getvalue()
    assert rc == 0
    # Themed status bar with REPLAY marker.
    assert "VOLI LLM | REPLAY" in text
    # Tool call + result blocks are reproduced.
    assert "[ TOOL CALL ]" in text
    assert "get_underlying_snapshot" in text
    assert "[ TOOL OK   ]" in text
    # Answer block.
    assert "[ ANSWER ]" in text
    assert "NVDA is around $200." in text
    # Trace id in the footer.
    assert "trace_id: tc_replay" in text


def test_voli_replay_json_mode_for_llm_companion(trace_dir: Path) -> None:
    import json as _json

    dump_llm_run(
        "tc_json",
        prompt="prompt",
        provider="openai",
        model="gpt-test",
        answer="answer text",
        stop_reason="end_turn",
        tool_calls=[],
        tool_results=[],
    )
    out = io.StringIO()
    rc = main(["replay", "--json", "tc_json"], out=out)
    payload = _json.loads(out.getvalue())
    assert rc == 0
    assert payload["provider"] == "openai"
    assert payload["model"] == "gpt-test"
    assert payload["answer"] == "answer text"


# ---- end-to-end: llm-ask --trace writes the companion ---------------------


@dataclass
class StubProvider(LLMProvider):
    """Single-step stub that emits one text delta and stops."""

    name: str = "stub"
    model: str = "stub-model"
    _started: bool = field(default=False, init=False)

    def start(self, *, system, tools, user_message, max_tokens=2048, temperature=0.2):
        self._started = True

    def step(self) -> Iterator[Any]:
        yield TextDelta(text="42.")
        yield StepComplete(stop_reason="end_turn")

    def submit_tool_results(self, results) -> None:
        pass


def test_llm_ask_with_trace_writes_companion(trace_dir: Path, monkeypatch) -> None:
    """Patch make_provider so the CLI uses our stub instead of trying to
    instantiate Anthropic. Then `voli llm-ask --trace ...` should write a
    .llm.json file the trace dir.
    """

    monkeypatch.setattr(
        "voli.llm.provider.make_provider", lambda name=None, model=None: StubProvider()
    )

    out = io.StringIO()
    rc = main(["llm-ask", "--no-color", "--trace", "the answer"], out=out)
    text = out.getvalue()
    assert rc == 0
    assert "replay companion:" in text

    # Companion file exists in trace_dir.
    companions = list(trace_dir.glob("*.llm.json"))
    assert len(companions) == 1


def test_llm_ask_with_skeptic_renders_block(trace_dir: Path, monkeypatch) -> None:
    """Stub provider emits a stale snapshot tool result; --skeptic should
    render a [ SKEPTIC ] block with STALE_SNAPSHOT.
    """

    import json as _json
    from datetime import UTC, datetime, timedelta

    old_iso = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    stale_payload = _json.dumps(
        {
            "snapshot": {
                "ticker": "NVDA",
                "spot": 100.0,
                "ts": old_iso,
                "source": "polygon",
            },
        }
    )

    @dataclass
    class StaleProvider(StubProvider):
        _step_index: int = field(default=0, init=False)

        def step(self) -> Iterator[Any]:
            if self._step_index == 0:
                self._step_index += 1
                yield ToolCallStart(
                    id="t1",
                    name="get_underlying_snapshot",
                    arguments={"ticker": "NVDA"},
                )
                yield StepComplete(stop_reason="tool_use")
            else:
                yield TextDelta(text="NVDA spot is $100.")
                yield StepComplete(stop_reason="end_turn")

    # Provider yields ToolCallStart -> the agent dispatches the call from
    # the registered toolset. Patch make_provider where the CLI imports it.
    monkeypatch.setattr(
        "voli.llm.provider.make_provider", lambda name=None, model=None: StaleProvider()
    )

    # Patch build_default_tools so the agent loop dispatches against our
    # stale-payload stub instead of the real Polygon-backed tools.
    from voli.llm.types import ToolDef

    def _patched_build(include_analytics: bool = True):
        return [
            ToolDef(
                name="get_underlying_snapshot",
                description="(test stub)",
                input_schema={
                    "type": "object",
                    "properties": {"ticker": {"type": "string"}},
                    "required": ["ticker"],
                },
                fn=lambda _args: stale_payload,
            ),
        ]

    import voli.llm

    monkeypatch.setattr(voli.llm, "build_default_tools", _patched_build)

    out = io.StringIO()
    rc = main(["llm-ask", "--no-color", "--skeptic", "what is NVDA spot?"], out=out)
    text = out.getvalue()
    assert rc == 0
    assert "[ SKEPTIC ]" in text
    assert "STALE_SNAPSHOT" in text
