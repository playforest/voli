"""LLM agent loop.

`llm_ask` drives a conversation between the LLM and the Voli tools until
the model finishes (`stop_reason != 'tool_use'`) or hits a step cap.
Yields the same neutral event types regardless of provider, so callers
(CLI, tests, future web UI) can stream output uniformly.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from .prompts import DEFAULT_SYSTEM_PROMPT
from .provider import LLMProvider
from .tools import build_default_tools
from .tools import execute as execute_tool
from .types import StepComplete, TextDelta, ToolCallStart, ToolDef, ToolResult


@dataclass(frozen=True)
class AgentConfig:
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    max_iterations: int = 6
    max_tokens: int = 2048
    temperature: float = 0.2


def llm_ask(
    prompt: str,
    *,
    provider: LLMProvider,
    tools: list[ToolDef] | None = None,
    config: AgentConfig | None = None,
) -> Iterator[TextDelta | ToolCallStart | ToolResult | StepComplete]:
    """Run the LLM agent loop. Yields events as they happen.

    The loop stops when the model finishes a step without requesting tools,
    or when `max_iterations` is exceeded (in which case we emit a final
    StepComplete with stop_reason='max_iterations').
    """

    cfg = config or AgentConfig()
    tools = tools or build_default_tools()

    provider.start(
        system=cfg.system_prompt,
        tools=tools,
        user_message=prompt,
        max_tokens=cfg.max_tokens,
        temperature=cfg.temperature,
    )

    for _iteration in range(cfg.max_iterations):
        pending: list[ToolCallStart] = []
        last_stop = "end_turn"
        for event in provider.step():
            yield event
            if isinstance(event, ToolCallStart):
                pending.append(event)
            elif isinstance(event, StepComplete):
                last_stop = event.stop_reason

        if not pending:
            return

        # Execute every pending tool call before stepping again.
        results: list[ToolResult] = []
        for call in pending:
            content = execute_tool(tools, call.name, call.arguments)
            result = ToolResult(id=call.id, name=call.name, content=content)
            results.append(result)
            yield result

        provider.submit_tool_results(results)

        # Defensive: a stop_reason other than 'tool_use' shouldn't happen
        # alongside tool calls, but if a provider misreports, bail rather
        # than infinite-loop.
        if last_stop not in ("tool_use", "end_turn"):
            yield StepComplete(stop_reason=last_stop)
            return

    yield StepComplete(stop_reason="max_iterations")


# ---- helpers for non-streaming callers ------------------------------------


@dataclass
class AgentResult:
    answer: str
    tool_calls: list[ToolCallStart]
    tool_results: list[ToolResult]
    stop_reason: str


def collect(events: Iterator[Any]) -> AgentResult:
    """Drain an event iterator into an AgentResult.

    Useful for tests / programmatic callers that don't need streaming.
    """

    text_buf: list[str] = []
    calls: list[ToolCallStart] = []
    results: list[ToolResult] = []
    stop = "end_turn"
    for ev in events:
        if isinstance(ev, TextDelta):
            text_buf.append(ev.text)
        elif isinstance(ev, ToolCallStart):
            calls.append(ev)
        elif isinstance(ev, ToolResult):
            results.append(ev)
        elif isinstance(ev, StepComplete):
            stop = ev.stop_reason
    return AgentResult(
        answer="".join(text_buf),
        tool_calls=calls,
        tool_results=results,
        stop_reason=stop,
    )
