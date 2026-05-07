# Extending Voli — LLM providers

`voli llm-ask` and `voli mcp-serve` use a small Protocol to talk to whatever
LLM you point them at. Anthropic and OpenAI ship in core; adding a third
(Gemini, Grok, Mistral, a local Ollama, ...) is a single-file job.

## What you implement

`voli.llm.provider.LLMProvider` is an abstract class with three methods:

```python
from abc import ABC, abstractmethod
from collections.abc import Iterator

from voli.llm.types import StepComplete, TextDelta, ToolCallStart, ToolDef, ToolResult


class LLMProvider(ABC):
    @abstractmethod
    def start(
        self, *, system: str, tools: list[ToolDef], user_message: str,
        max_tokens: int = 2048, temperature: float = 0.2,
    ) -> None:
        """Initialise a new conversation. Replaces any prior state."""

    @abstractmethod
    def step(self) -> Iterator[TextDelta | ToolCallStart | StepComplete]:
        """One inference step. Stream text deltas, then tool-use blocks,
        then exactly one StepComplete with the model's stop_reason."""

    @abstractmethod
    def submit_tool_results(self, results: list[ToolResult]) -> None:
        """Append tool execution results to the conversation."""
```

The tool-use loop in `voli.llm.agent` calls these in turn until `step()`
ends with a non-tool stop reason. Events you yield are the **neutral** type
set in `voli.llm.types` — the agent loop never sees Anthropic or OpenAI
SDK objects.

## Reference implementations

The two bundled providers are the canonical examples:

| File | What it shows |
| --- | --- |
| [`src/voli/llm/anthropic_provider.py`](https://github.com/playforest/voli/blob/main/src/voli/llm/anthropic_provider.py) | Streaming via the Anthropic SDK, tool-use parsing, multi-turn message threading. |
| [`src/voli/llm/openai_provider.py`](https://github.com/playforest/voli/blob/main/src/voli/llm/openai_provider.py) | Same surface against the OpenAI Responses API; arguments arrive as JSON strings instead of dicts. |

A new provider should mirror their structure. Most of the work is mapping
the vendor's streaming event shape into Voli's `TextDelta` /
`ToolCallStart` / `StepComplete` events.

## Wiring it up today

`voli.llm.provider.make_provider` is the factory the CLI calls. Today it
hard-codes the two bundled providers:

```python
def make_provider(name: str | None = None, *, model: str | None = None) -> LLMProvider:
    name = (name or get_default_provider_name()).lower()
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(model=model)
    if name == "openai":
        from .openai_provider import OpenAIProvider
        return OpenAIProvider(model=model)
    raise ValueError(f"Unknown LLM provider {name!r}. ...")
```

To add a third in a fork, drop your `MyLLMProvider` class in a new module
and add a branch to `make_provider`. The CLI flag (`--provider`) and env
var (`$VOLI_LLM_PROVIDER`) will accept the new name.

!!! info "Roadmap: entry-point discovery for LLM providers"

    The data-provider layer auto-discovers any package exposing a
    [`voli.data_providers` entry point](data-providers.md#shipping-as-a-pip-installable-package);
    the LLM layer doesn't yet but will mirror that pattern in a future
    release. Track the work in the project README.

## Sharp edges

- **Stream text first, tool calls second, then `StepComplete`.** The agent
  loop assumes this ordering. Buffering everything until end of turn works
  too — but the live tool-call rendering in the CLI relies on the streaming
  order to feel responsive.
- **Tool args must arrive as a plain `dict`.** The Anthropic SDK gives you
  a dict already; the OpenAI Responses API gives you a JSON string — see
  `_to_neutral_arguments` in `provider.py` for the canonical conversion.
- **Lazy-import the SDK.** Voli's lean install doesn't include any LLM
  SDKs. Put `from anthropic import ...` inside the provider methods (or at
  the top of the provider module) so a user without your SDK installed can
  still run `voli ask` without a `ModuleNotFoundError` on import.
- **`stop_reason` matters.** If you emit `stop_reason="tool_use"` the agent
  will execute tools and call `submit_tool_results`. Any other value ends
  the loop.

## See also

- [Data providers](data-providers.md) — same plug-and-play story for
  vendor-side options data.
- [LLM-driven agent](../examples/llm-ask.md) — what the loop does once a
  provider is wired in.
