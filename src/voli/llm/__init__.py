"""LLM-driven agent: an LLM (Claude or GPT) plans + answers using Voli tools.

This is an alternative to the rule-based `voli.agent` pipeline. Both share
the same tool layer (`voli.tools.polygon_tools`) so they can never disagree
on the underlying data.

Public surface:
  * `llm_ask(prompt, provider, tools, ...)` - the agent loop. Yields events.
  * `build_default_tools()` - the four Polygon tools as ToolDef.
  * `AnthropicProvider`, `OpenAIProvider` - provider implementations.
  * Event types: `TextDelta`, `ToolCallStart`, `ToolResult`, `StepComplete`.
"""

from __future__ import annotations

from .agent import AgentConfig, llm_ask
from .provider import LLMProvider
from .tools import build_default_tools
from .types import StepComplete, TextDelta, ToolCallStart, ToolDef, ToolResult

__all__ = [
    "AgentConfig",
    "LLMProvider",
    "StepComplete",
    "TextDelta",
    "ToolCallStart",
    "ToolDef",
    "ToolResult",
    "build_default_tools",
    "llm_ask",
]
