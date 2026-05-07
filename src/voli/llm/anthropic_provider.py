"""Anthropic Claude implementation of LLMProvider.

Lazy-imports the `anthropic` SDK so users on the lean install don't pay
for the dep. Defaults to claude-sonnet-4-6 (good tool-use latency / cost /
quality balance); override with --model on the CLI or VOLI_LLM_MODEL env.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

from .provider import LLMProvider, _to_neutral_arguments
from .types import StepComplete, TextDelta, ToolCallStart, ToolDef, ToolResult

DEFAULT_MODEL = "claude-sonnet-4-6"


def _require_sdk():
    try:
        import anthropic
    except ImportError as exc:
        raise ImportError(
            "Anthropic provider requires the 'anthropic' package.\n"
            "Install with: poetry install -E anthropic   (or -E llm for both)."
        ) from exc
    return anthropic


def _to_anthropic_tools(tools: list[ToolDef]) -> list[dict[str, Any]]:
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": t.input_schema,
        }
        for t in tools
    ]


class AnthropicProvider(LLMProvider):
    """Wraps anthropic.Anthropic() with a stateful conversation."""

    name = "anthropic"

    def __init__(self, *, model: str | None = None, api_key: str | None = None) -> None:
        anthropic = _require_sdk()
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self.model = model or os.environ.get("VOLI_LLM_MODEL") or DEFAULT_MODEL

        # Per-conversation state, populated by start().
        self._system: str = ""
        self._tools: list[dict[str, Any]] = []
        self._messages: list[dict[str, Any]] = []
        self._max_tokens: int = 2048
        self._temperature: float = 0.2

    # ---- LLMProvider --------------------------------------------------------

    def start(
        self,
        *,
        system: str,
        tools: list[ToolDef],
        user_message: str,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> None:
        self._system = system
        self._tools = _to_anthropic_tools(tools)
        self._messages = [{"role": "user", "content": user_message}]
        self._max_tokens = max_tokens
        self._temperature = temperature

    def step(self) -> Iterator[TextDelta | ToolCallStart | StepComplete]:
        # Anthropic's streaming helper accumulates content blocks for us. We
        # iterate text deltas live and emit ToolCallStart once a tool_use
        # block has its full input.
        with self._client.messages.stream(
            model=self.model,
            system=self._system,
            tools=self._tools,
            messages=self._messages,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
        ) as stream:
            for event in stream:
                # The SDK exposes typed events; we only care about a few.
                etype = getattr(event, "type", None)
                if etype == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    text = getattr(delta, "text", None)
                    if text:
                        yield TextDelta(text=text)
                # Tool-use blocks come through as input_json_delta events, but
                # the SDK assembles them into the final message. We grab them
                # from the assembled message after the stream closes.
            final = stream.get_final_message()

        # Persist the assistant turn in our message list (so the next step
        # / submit_tool_results sees the right history).
        assistant_content = []
        tool_calls: list[ToolCallStart] = []
        for block in final.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                assistant_content.append({"type": "text", "text": block.text})
            elif btype == "tool_use":
                args = _to_neutral_arguments(getattr(block, "input", {}))
                assistant_content.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": dict(args),
                    }
                )
                tool_calls.append(ToolCallStart(id=block.id, name=block.name, arguments=args))
            else:
                # Forward unknown block types verbatim so we don't lose state.
                assistant_content.append(
                    {"type": btype, **getattr(block, "model_dump", lambda: {})()}
                )

        self._messages.append({"role": "assistant", "content": assistant_content})

        yield from tool_calls
        yield StepComplete(stop_reason=getattr(final, "stop_reason", "end_turn") or "end_turn")

    def submit_tool_results(self, results: list[ToolResult]) -> None:
        """Append tool results as a user-role message (Anthropic spec)."""

        content = [
            {
                "type": "tool_result",
                "tool_use_id": r.id,
                "content": r.content,
                "is_error": r.is_error,
            }
            for r in results
        ]
        self._messages.append({"role": "user", "content": content})
