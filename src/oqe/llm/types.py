"""Provider-neutral data classes shared across Anthropic + OpenAI.

The agent loop iterates a stream of these events; each provider is
responsible for converting its native streaming format into this shape.
That keeps the agent / CLI / tests free of any provider-specific code.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolDef:
    """One callable tool the LLM can invoke.

    `input_schema` is JSON-schema describing the tool's input. Each provider
    converts this into its own tool/function spec at request time.

    `fn` receives the parsed args dict and returns a string (or any
    JSON-serialisable value); whatever it returns goes back to the LLM as
    the tool result.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    fn: Callable[[dict[str, Any]], Any]


# ---- streaming events ------------------------------------------------------


@dataclass(frozen=True)
class TextDelta:
    """A chunk of model-generated text (the answer)."""

    text: str


@dataclass(frozen=True)
class ToolCallStart:
    """The model has decided to call a tool. `arguments` is already parsed."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    """Result of executing a ToolCallStart. Sent back to the model."""

    id: str
    name: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class StepComplete:
    """One inference step finished. `stop_reason` mirrors the API field
    (e.g. "tool_use", "end_turn", "max_tokens").
    """

    stop_reason: str
