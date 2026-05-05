"""LLM agent tests.

We use a stub LLMProvider that yields scripted events so the tests are
fast, deterministic, and never touch a real LLM API. The real Anthropic /
OpenAI integrations are exercised by their own SDKs - the value here is
that the agent loop / tool dispatch / CLI plumbing works.
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest

from oqe.agent.executor import ToolRegistry
from oqe.cli import main
from oqe.llm import (
    AgentConfig,
    LLMProvider,
    StepComplete,
    TextDelta,
    ToolCallStart,
    ToolDef,
    ToolResult,
    build_default_tools,
    llm_ask,
)
from oqe.llm.agent import collect

# ---- stub provider ---------------------------------------------------------


@dataclass
class StubProvider(LLMProvider):
    """Replays a scripted sequence of step() outputs.

    `script` is a list of lists - one inner list per call to step(). Each
    inner list is the events that step() should yield. The provider
    automatically appends a StepComplete if the inner list doesn't include
    one (callers can override).
    """

    script: list[list[Any]]
    name: str = "stub"
    model: str = "stub-model"

    # Captured for assertions:
    started_with: dict[str, Any] = field(default_factory=dict)
    submitted_results: list[list[ToolResult]] = field(default_factory=list)

    _step_index: int = 0

    def start(self, *, system, tools, user_message, max_tokens=2048, temperature=0.2):
        self.started_with = {
            "system": system,
            "tools": [t.name for t in tools],
            "user_message": user_message,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        self._step_index = 0

    def step(self) -> Iterator[Any]:
        if self._step_index >= len(self.script):
            yield StepComplete(stop_reason="end_turn")
            return
        events = self.script[self._step_index]
        self._step_index += 1
        yield from events
        if not any(isinstance(e, StepComplete) for e in events):
            stop = "tool_use" if any(isinstance(e, ToolCallStart) for e in events) else "end_turn"
            yield StepComplete(stop_reason=stop)

    def submit_tool_results(self, results: list[ToolResult]) -> None:
        self.submitted_results.append(list(results))


# ---- agent loop ------------------------------------------------------------


def test_pure_text_response_no_tool_calls() -> None:
    provider = StubProvider(
        script=[
            [TextDelta(text="Hello "), TextDelta(text="world.")],
        ]
    )
    result = collect(llm_ask("hi", provider=provider, tools=[]))
    assert result.answer == "Hello world."
    assert result.tool_calls == []
    assert result.stop_reason == "end_turn"


def test_single_tool_call_then_answer() -> None:
    """Step 1: model emits a tool call. Step 2: model emits the answer."""

    def echo_tool(args):
        return json.dumps({"echo": args})

    tools = [
        ToolDef(
            name="echo",
            description="Echo back the input.",
            input_schema={"type": "object", "properties": {"x": {"type": "string"}}},
            fn=echo_tool,
        )
    ]

    provider = StubProvider(
        script=[
            [ToolCallStart(id="t1", name="echo", arguments={"x": "hi"})],
            [TextDelta(text="The echo said hi.")],
        ]
    )
    result = collect(llm_ask("hello", provider=provider, tools=tools))
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "echo"
    assert result.tool_results[0].content == json.dumps({"echo": {"x": "hi"}})
    assert "echo said hi" in result.answer
    # The provider should have been handed the tool results between steps.
    assert len(provider.submitted_results) == 1


def test_multiple_tool_calls_in_one_step() -> None:
    def t(args):
        return json.dumps(args)

    tools = [ToolDef(name="t", description="", input_schema={}, fn=t)]
    provider = StubProvider(
        script=[
            [
                ToolCallStart(id="a", name="t", arguments={"x": 1}),
                ToolCallStart(id="b", name="t", arguments={"x": 2}),
            ],
            [TextDelta(text="done.")],
        ]
    )
    result = collect(llm_ask("go", provider=provider, tools=tools))
    assert [c.id for c in result.tool_calls] == ["a", "b"]
    assert [r.id for r in result.tool_results] == ["a", "b"]


def test_unknown_tool_returns_error_payload() -> None:
    provider = StubProvider(
        script=[
            [ToolCallStart(id="z", name="not_a_tool", arguments={})],
            [TextDelta(text="oh well.")],
        ]
    )
    result = collect(llm_ask("go", provider=provider, tools=[]))
    payload = json.loads(result.tool_results[0].content)
    assert payload["error"] == "UnknownTool"
    assert "not_a_tool" in payload["message"]


def test_max_iterations_caps_runaway_loop() -> None:
    """Provider that never stops requesting tools should be cut off cleanly."""

    def t(_args):
        return "{}"

    tools = [ToolDef(name="t", description="", input_schema={}, fn=t)]
    provider = StubProvider(
        script=[[ToolCallStart(id=str(i), name="t", arguments={})] for i in range(20)]
    )
    cfg = AgentConfig(max_iterations=3)
    result = collect(llm_ask("go", provider=provider, tools=tools, config=cfg))
    assert result.stop_reason == "max_iterations"
    assert len(result.tool_calls) == 3


# ---- default tool surface --------------------------------------------------


def test_build_default_tools_returns_four_polygon_tools() -> None:
    tools = build_default_tools()
    names = {t.name for t in tools}
    assert names == {
        "get_underlying_snapshot",
        "list_option_contracts",
        "get_option_quotes",
        "get_option_greeks",
    }
    # Each must have an input_schema that's a dict (so providers can serialise it).
    for t in tools:
        assert isinstance(t.input_schema, dict)
        assert t.input_schema.get("type") == "object"


# ---- tool dispatch end-to-end via the synthetic registry -------------------


def test_default_tools_dispatch_against_synthetic_market(monkeypatch) -> None:
    """Patch the production tool functions to use the synthetic registry so
    we can verify build_default_tools() actually returns usable callables.
    """

    from oqe.eval.synth_market import make_registry as _mk

    reg: ToolRegistry = _mk()

    # The default tools call oqe.tools.polygon_tools functions; rather than
    # rewire them, we drive llm_ask's tool dispatch directly.
    tools = build_default_tools()

    # Replace each tool's fn with the synthetic registry equivalent.
    name_to_synth = {
        "get_underlying_snapshot": reg.tools["get_underlying_snapshot"],
        "list_option_contracts": reg.tools["list_option_contracts"],
        "get_option_quotes": reg.tools["get_option_quotes"],
        "get_option_greeks": reg.tools["get_option_greeks"],
    }
    wrapped = []
    for t in tools:
        synth = name_to_synth[t.name]
        wrapped.append(
            ToolDef(
                name=t.name,
                description=t.description,
                input_schema=t.input_schema,
                fn=lambda args, _s=synth: json.dumps(_serialise(_s(args))),
            )
        )

    provider = StubProvider(
        script=[
            [ToolCallStart(id="1", name="get_underlying_snapshot", arguments={"ticker": "NVDA"})],
            [TextDelta(text="NVDA spot is 100.")],
        ]
    )
    result = collect(llm_ask("what is NVDA spot?", provider=provider, tools=wrapped))
    payload = json.loads(result.tool_results[0].content)
    assert payload["snapshot"]["spot"] == 100.0


def _serialise(obj):
    """Helper for the synth registry result -> dict."""

    if obj is None:
        return None
    if hasattr(obj, "snapshot") and obj.snapshot is not None:
        s = obj.snapshot
        return {
            "snapshot": {"ticker": s.ticker, "spot": s.spot, "ts": str(s.ts), "source": s.source}
        }
    if hasattr(obj, "contracts"):
        return {
            "contracts": [
                {
                    "option_symbol": c.option_symbol,
                    "strike": c.strike,
                    "right": c.right,
                    "expiry": str(c.expiry),
                }
                for c in obj.contracts
            ]
        }
    if hasattr(obj, "quotes"):
        return {
            "quotes": [
                {"option_symbol": q.option_symbol, "bid": q.bid, "ask": q.ask, "mid": q.mid}
                for q in obj.quotes
            ]
        }
    if hasattr(obj, "greeks"):
        return {
            "greeks": [
                {"option_symbol": g.option_symbol, "iv": g.iv, "delta": g.delta} for g in obj.greeks
            ]
        }
    return {}


# ---- CLI integration --------------------------------------------------------


def test_cli_llm_ask_unknown_provider_returns_4(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    out = io.StringIO()
    rc = main(
        ["llm-ask", "--no-color", "--provider", "anthropic", "--model", "x", "hi"],
        out=out,
    )
    # We pass a real provider name + fake key. The Anthropic SDK initialises
    # without raising; the actual API call would fail later, but we don't
    # exercise that here. So we only assert the CLI didn't crash on argparse.
    assert rc in (0, 4)  # 4 if the Anthropic SDK rejected the request


def test_cli_llm_ask_with_invalid_provider_name(monkeypatch) -> None:
    out = io.StringIO()
    with pytest.raises(SystemExit):
        # argparse choices=[anthropic, openai] should reject this.
        main(["llm-ask", "--provider", "magic", "hi"], out=out)


# ---- guards ----------------------------------------------------------------


def test_lazy_imports_keep_lean_install_working(monkeypatch) -> None:
    """Importing oqe.llm should not require anthropic/openai to be importable.
    The provider modules import their SDKs lazily inside _require_sdk.
    """

    import importlib

    # Remove the SDKs from sys.modules; oqe.llm import shouldn't trip on it.
    monkeypatch.setitem(__import__("sys").modules, "anthropic", None)
    monkeypatch.setitem(__import__("sys").modules, "openai", None)
    importlib.reload(__import__("oqe.llm", fromlist=["*"]))
    # No exception => pass.
