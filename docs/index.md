---
title: Home
hide:
  - navigation
---

# Voli

A Python library and CLI that answers natural-language questions about an
equity option chain (chain slices, IV term structure, skew, basic greeks)
with a runtime guardrail that refuses to invent numbers.

The same underlying tools are exposed through four entry points: a
rule-based CLI, an LLM-driven CLI, an MCP server (Claude Desktop /
claude.ai web), and a Python library you can import directly.

**Pluggable data and LLM providers.** Polygon ships as the default data
provider, with Anthropic and OpenAI for the LLM layer. Forks can add
yfinance, Tradier, Gemini, etc. behind small Protocols. See
[Extending Voli](extending/data-providers.md).

<div class="grid cards" markdown>

-   :material-flash: __Fast to try__

    ---

    Install with Poetry, drop a Polygon key in `.env`, ask a question.

    [:octicons-arrow-right-24: Installation](getting-started/installation.md)

-   :material-puzzle: __Pluggable providers__

    ---

    Polygon by default; swap in yfinance / Tradier / IBKR by writing four
    small functions. Same story for the LLM layer.

    [:octicons-arrow-right-24: Extending Voli](extending/data-providers.md)

-   :material-target: __Grounded answers__

    ---

    Every numeric token in a summary must trace back to a tool call or an
    analytics function. The writer raises rather than inventing.

    [:octicons-arrow-right-24: Guardrails](architecture/guardrails.md)

-   :material-robot: __LLM-driven__

    ---

    Plug in Claude or GPT and the LLM drives the same Voli tools, streaming
    its tool calls as it works.

    [:octicons-arrow-right-24: LLM-driven agent](examples/llm-ask.md)

-   :material-link-variant: __MCP server__

    ---

    Connect to Claude Desktop or claude.ai web in two minutes; Claude can
    then call your local Voli tools mid-conversation.

    [:octicons-arrow-right-24: MCP server](examples/mcp.md)

-   :material-palette: __Bloomberg-style CLI__

    ---

    Twelve built-in colour themes. Sensible defaults, easy to switch, no emojis.

    [:octicons-arrow-right-24: Themes](cli/themes.md)

-   :material-test-tube: __Reproducible eval__

    ---

    20-case JSONL dataset; per-case checks for tool sequence, table type,
    Facts keys, and numeric metrics within tolerance.

    [:octicons-arrow-right-24: Eval Harness](eval/harness.md)

</div>

## Quickstart

=== "Rule-based CLI"

    ```bash
    poetry install
    cp .env.example .env  # edit POLYGON_API_KEY=pk_...
    poetry run voli ask "NVDA ATM IV this week vs next week"
    ```

=== "LLM-driven CLI"

    ```bash
    poetry install -E llm   # or -E anthropic / -E openai
    # add ANTHROPIC_API_KEY or OPENAI_API_KEY to .env
    poetry run voli llm-ask "How does NVDA's IV term structure compare to QQQ's?"
    ```

=== "MCP server (Claude Desktop)"

    ```bash
    poetry install -E mcp
    # then point Claude Desktop's claude_desktop_config.json at:
    #   command: poetry, args: ["run", "voli", "mcp-serve"]
    # see the MCP page below for the full snippet.
    ```

=== "Python"

    ```python
    from voli.agent import answer_question

    resp = answer_question("NVDA ATM IV this week vs next week")
    print(resp.summary)
    print(resp.facts["front_iv"], resp.facts["next_iv"])
    ```

=== "Docker"

    ```bash
    docker compose -f docker/docker-compose.yml run --rm \
      voli ask "NVDA ATM IV this week vs next week"
    ```

## API keys

| Variable | What for | Where to get it |
| --- | --- | --- |
| `POLYGON_API_KEY` | All live data (required) | [polygon.io](https://polygon.io/) |
| `ANTHROPIC_API_KEY` | `voli llm-ask --provider anthropic` and the MCP server when chatting via Claude | [console.anthropic.com](https://console.anthropic.com) |
| `OPENAI_API_KEY` | `voli llm-ask --provider openai` | [platform.openai.com](https://platform.openai.com) |

Set them in `.env` (auto-loaded) or your shell. See
[Installation](getting-started/installation.md) for the full env-var
reference.

## Sample output

```text
================================================================================
 VOLI | TICKER: NVDA | CATEGORY: TERM_STRUCTURE | OK
================================================================================
[ SUMMARY ]
NVDA ATM IV term structure: front IV 0.3318 vs next IV 0.3457 at strike 200.0
(diff 0.0139).

[ TERM STRUCTURE ]
EXPIRY      |  ATM_STRIKE  |  ATM_IV
------------------------------------
2026-05-09  |         200  |  0.3318
2026-05-16  |         200  |  0.3457

[ FACTS ]
TICKER        NVDA
SPOT          value=199.8450  ts=2026-05-05T13:09:04Z  source=polygon
RIGHT_USED    call
ATM_STRIKE    200
FRONT_EXPIRY  2026-05-09
NEXT_EXPIRY   2026-05-16
FRONT_IV      0.3318
NEXT_IV       0.3457
================================================================================
```

## Subcommands at a glance

| Command | Purpose |
| --- | --- |
| [`voli ask`](cli/overview.md) | Rule-based agent. Deterministic, fast, no LLM cost. |
| [`voli ask-many`](examples/batch.md) | Same prompt across multiple tickers, comparison table. |
| [`voli llm-ask`](examples/llm-ask.md) | LLM (Claude / GPT) drives the Voli tools. Streams chain-of-thought. |
| [`voli mcp-serve`](examples/mcp.md) | MCP server for Claude Desktop / claude.ai. |
| [`voli replay`](examples/replay.md) | Re-render a stored answer offline (rule-based or LLM). |
| [`voli themes`](cli/themes.md) | Browse / preview the 12 colour palettes. |

## What it answers

| Category | Example prompt |
| --- | --- |
| **Chain lookup** | _"List NVDA calls for 2026-05-16 between 90 and 110."_ |
| **IV term structure** | _"NVDA ATM IV this week vs next week."_ |
| **Skew** | _"What's the skew slope across strikes for TSLA next week?"_ |
| **Greeks** | _"What are the greeks of the NVDA 2026-05-16 100C?"_ |

The rule-based agent refuses anything that requires advice, prediction, or
execution (_"Should I buy NVDA calls?"_) and offers supported rewrites
instead. The LLM-driven agent can reason about open-ended comparisons
("How does NVDA compare to QQQ?") that the rule-based path doesn't
template.

## Where to go next

- [Installation](getting-started/installation.md): set up the package and keys.
- [Your first query](getting-started/first-query.md): walkthrough.
- [CLI Reference](cli/overview.md): every flag and subcommand.
- [LLM-driven agent](examples/llm-ask.md): Claude / GPT with streaming.
- [MCP server](examples/mcp.md): Claude Desktop / claude.ai integration.
- [Examples cookbook](examples/term-structure.md): recipes per category.
- [Architecture](architecture/orchestrator.md): how the pieces fit.
