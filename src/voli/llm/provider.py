"""Provider-neutral LLM interface.

Each concrete provider (Anthropic, OpenAI, ...) is a stateful object: it
holds the conversation message list internally and exposes a small
verb-based API:

  start(system, tools, initial_user)   - begin a new conversation.
  step()                                - one inference step; yields events.
  submit_tool_results(results)          - append tool results to the convo.

The agent loop in `agent.py` calls these in turn until `step()` ends with
a non-tool stop reason.

This shape makes it trivial to add a third provider later: just implement
the three methods and yield events from the neutral `voli.llm.types` set.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import Any

from .types import StepComplete, TextDelta, ToolCallStart, ToolDef, ToolResult


class LLMProvider(ABC):
    """Abstract base for LLM providers."""

    @abstractmethod
    def start(
        self,
        *,
        system: str,
        tools: list[ToolDef],
        user_message: str,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> None:
        """Initialise a new conversation. Replaces any prior state."""

    @abstractmethod
    def step(self) -> Iterator[TextDelta | ToolCallStart | StepComplete]:
        """Run one inference step and stream events.

        The provider must:
          * yield TextDelta for each text chunk
          * yield ToolCallStart for each completed tool_use block (with
            arguments already parsed)
          * yield exactly one StepComplete at the end with the model's
            stop_reason

        After a StepComplete with stop_reason=='tool_use', the caller will
        execute the tools and call submit_tool_results before stepping again.
        """

    @abstractmethod
    def submit_tool_results(self, results: list[ToolResult]) -> None:
        """Append tool execution results to the conversation."""


def get_default_provider_name() -> str:
    """Pick a provider when the user didn't specify.

    Order: explicit VOLI_LLM_PROVIDER env var > 'anthropic' if ANTHROPIC_API_KEY
    is set > 'openai' if OPENAI_API_KEY is set > 'anthropic' (fail informatively
    later when the key check runs).
    """

    import os

    explicit = os.environ.get("VOLI_LLM_PROVIDER")
    if explicit:
        return explicit.lower()
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return "anthropic"


def make_provider(name: str | None = None, *, model: str | None = None) -> LLMProvider:
    """Factory that returns the configured provider instance.

    Lazy-imports the concrete provider so callers don't pay the dep cost
    for the one they're not using. Bundled providers (``anthropic``,
    ``openai``) resolve directly; any other name is looked up via the
    ``voli.llm_providers`` entry-point group, so a fork can ship
    ``pip install voli-gemini`` and have ``--provider gemini`` light up
    automatically.
    """

    name = (name or get_default_provider_name()).lower()
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(model=model)
    if name == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(model=model)

    # Third-party providers via entry points.
    cls = _load_entry_point_provider(name)
    if cls is not None:
        return cls(model=model)

    available = ", ".join(["anthropic", "openai", *sorted(_entry_point_provider_names())])
    raise ValueError(
        f"Unknown LLM provider {name!r}. Available: {available}. "
        "Install a provider package (e.g. pip install voli-gemini) or "
        "see docs/extending/llm-providers.md."
    )


def list_llm_providers() -> list[str]:
    """Return the names of all currently resolvable LLM providers.

    Includes the two bundled providers plus any installed via the
    ``voli.llm_providers`` entry-point group.
    """

    return sorted({"anthropic", "openai", *_entry_point_provider_names()})


# ---------------------------------------------------------------------------
# Entry-point discovery (mirrors voli.providers for data providers)
# ---------------------------------------------------------------------------

_ENTRY_POINT_GROUP = "voli.llm_providers"
_entry_points_cache: dict[str, type[LLMProvider]] | None = None


def _entry_points() -> dict[str, type[LLMProvider]]:
    """Return ``{name: class}`` from the ``voli.llm_providers`` group.

    Cached for the process lifetime; failures during ``ep.load()`` are
    swallowed so a broken third-party plugin can't take down the CLI.
    """

    global _entry_points_cache
    if _entry_points_cache is not None:
        return _entry_points_cache
    try:
        from importlib.metadata import entry_points
    except ImportError:  # pragma: no cover
        _entry_points_cache = {}
        return _entry_points_cache
    try:
        eps = entry_points(group=_ENTRY_POINT_GROUP)
    except TypeError:
        eps = entry_points().get(_ENTRY_POINT_GROUP, [])  # type: ignore[attr-defined]
    out: dict[str, type[LLMProvider]] = {}
    for ep in eps:
        try:
            obj = ep.load()
            if isinstance(obj, type):
                out[ep.name] = obj
        except Exception:  # noqa: BLE001
            continue
    _entry_points_cache = out
    return out


def _load_entry_point_provider(name: str) -> type[LLMProvider] | None:
    return _entry_points().get(name)


def _entry_point_provider_names() -> list[str]:
    return list(_entry_points().keys())


def _to_neutral_arguments(raw: Any) -> dict[str, Any]:
    """Best-effort conversion of provider-specific tool arg payloads into a
    plain dict. Anthropic gives a dict; OpenAI gives a JSON string.
    """

    import json

    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"_raw": raw}
        return parsed if isinstance(parsed, dict) else {"_value": parsed}
    if raw is None:
        return {}
    return {"_value": raw}
