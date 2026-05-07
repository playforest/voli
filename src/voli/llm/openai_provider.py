"""OpenAI implementation of LLMProvider (Chat Completions API + function
calling tool-use).

Lazy-imports the `openai` package. Defaults to gpt-4.1-mini; override
with --model or VOLI_LLM_MODEL.

Implementation note: OpenAI's streaming API delivers function-call args
as concatenated chunks. We accumulate per tool_call_id, parse the JSON
once the stream ends, and emit a single ToolCallStart per call (matching
Anthropic's behaviour).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any

from .provider import LLMProvider, _to_neutral_arguments
from .types import StepComplete, TextDelta, ToolCallStart, ToolDef, ToolResult

DEFAULT_MODEL = "gpt-4.1-mini"


def _require_sdk():
    try:
        import openai
    except ImportError as exc:
        raise ImportError(
            "OpenAI provider requires the 'openai' package.\n"
            "Install with: poetry install -E openai   (or -E llm for both)."
        ) from exc
    return openai


def _to_openai_tools(tools: list[ToolDef]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        }
        for t in tools
    ]


class OpenAIProvider(LLMProvider):
    """Wraps openai.OpenAI() with a stateful conversation."""

    name = "openai"

    def __init__(self, *, model: str | None = None, api_key: str | None = None) -> None:
        openai = _require_sdk()
        self._openai = openai
        self._client = openai.OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))
        self.model = model or os.environ.get("VOLI_LLM_MODEL") or DEFAULT_MODEL

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
        self._tools = _to_openai_tools(tools)
        self._messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ]
        self._max_tokens = max_tokens
        self._temperature = temperature

    def step(self) -> Iterator[TextDelta | ToolCallStart | StepComplete]:
        # Per-tool-call accumulators (id is stable across deltas).
        tool_buf: dict[int, dict[str, Any]] = {}
        text_buf: list[str] = []
        finish_reason = "stop"

        stream = self._client.chat.completions.create(
            model=self.model,
            messages=self._messages,
            tools=self._tools or None,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            stream=True,
        )
        for chunk in stream:
            choice = chunk.choices[0] if chunk.choices else None
            if choice is None:
                continue
            delta = choice.delta
            if delta.content:
                text_buf.append(delta.content)
                yield TextDelta(text=delta.content)
            for call in delta.tool_calls or []:
                idx = call.index
                slot = tool_buf.setdefault(idx, {"id": None, "name": None, "args": ""})
                if call.id:
                    slot["id"] = call.id
                if call.function and call.function.name:
                    slot["name"] = call.function.name
                if call.function and call.function.arguments:
                    slot["args"] += call.function.arguments
            if choice.finish_reason:
                finish_reason = choice.finish_reason

        # Build the assistant message we'll append to history.
        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": "".join(text_buf) if text_buf else None,
        }
        if tool_buf:
            assistant_message["tool_calls"] = [
                {
                    "id": slot["id"],
                    "type": "function",
                    "function": {
                        "name": slot["name"],
                        "arguments": slot["args"] or "{}",
                    },
                }
                for _, slot in sorted(tool_buf.items())
            ]
        self._messages.append(assistant_message)

        # Emit ToolCallStart events for each tool call in stable order.
        for _, slot in sorted(tool_buf.items()):
            args = _to_neutral_arguments(slot["args"])
            yield ToolCallStart(id=slot["id"], name=slot["name"], arguments=args)

        # Map OpenAI finish_reason to a stop_reason that mirrors Anthropic.
        stop_reason = (
            "tool_use" if tool_buf else ("end_turn" if finish_reason == "stop" else finish_reason)
        )
        yield StepComplete(stop_reason=stop_reason)

    def submit_tool_results(self, results: list[ToolResult]) -> None:
        """OpenAI expects one role='tool' message per tool_call_id."""

        for r in results:
            self._messages.append(
                {
                    "role": "tool",
                    "tool_call_id": r.id,
                    "content": r.content
                    if not r.is_error
                    else json.dumps({"error": "tool_error", "message": r.content}),
                }
            )
