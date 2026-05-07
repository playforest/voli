# Voli

> A Python library + CLI that answers natural-language questions about an
> equity option chain — chain slices, IV term structure, skew, greeks —
> with a "no invented numbers" guarantee.
>
> Same tools, four entry points: rule-based CLI, LLM-driven CLI, MCP
> server (Claude Desktop / claude.ai), and direct Python imports.
>
> **Pluggable data providers** (Polygon ships as the default) and
> **pluggable LLM providers** (Anthropic + OpenAI ship in core). Forks
> can add yfinance, Tradier, Gemini, etc. with a few small files —
> see [Extending Voli](docs/extending/data-providers.md).

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

## Why Voli?

- **Grounded.** Every numeric claim in the answer must come from a tool call
  or a centralised analytics function — the writer enforces a runtime
  guardrail and refuses to emit invented numbers.
- **Pluggable.** Data providers live behind a small Protocol — Polygon ships
  as the default; forks can add yfinance, Tradier, IBKR, ORATS by writing
  four functions. LLM providers (Anthropic + OpenAI) plug in the same way.
- **Deterministic** rule-based path. A heuristic planner produces the same
  plan for the same prompt; analytics are pure functions over the chain
  snapshot. Same prompt + same cache window = same answer.
- **LLM-driven** path. Claude or GPT can drive the same toolset for free-form
  questions; the LLM streams its tool calls live as it works.
- **Bloomberg-style CLI.** Twelve bundled colour themes; defaults to a
  Bloomberg-Terminal-inspired orange/amber on black.
- **MCP server**. Connect to Claude Desktop or claude.ai web in two minutes
  and ask options questions in chat.
- **Reproducible eval.** A 20-case JSONL dataset and a runner that scores
  per-case checks (tool sequence, table type, Facts keys, numeric metrics)
  and exits non-zero on any regression.

## Quickstart

### 1. Install

```bash
git clone https://github.com/playforest/voli
cd voli
poetry install
```

### 2. Add your API keys

```bash
cp .env.example .env
```

Edit `.env`:

```bash
# Required for live Polygon queries
POLYGON_API_KEY=pk_your_polygon_key

# Optional - only needed for `voli llm-ask` and the MCP server
ANTHROPIC_API_KEY=sk-ant-your_anthropic_key   # for Claude
OPENAI_API_KEY=sk-your_openai_key             # for GPT
```

The CLI loads `.env` automatically on startup. Anything in your shell
environment wins over `.env`.

### 3. Pick the entry point you want

=== "Rule-based CLI"

    Always available, no extra installs needed:

    ```bash
    poetry run voli ask "NVDA ATM IV this week vs next week"
    ```

=== "LLM-driven CLI"

    Pick a provider and install its extra:

    ```bash
    poetry install -E anthropic   # Claude (Sonnet 4.6 by default)
    poetry install -E openai      # GPT (gpt-4.1-mini by default)
    poetry install -E llm         # both

    poetry run voli llm-ask "How does NVDA's IV term structure compare to QQQ's?"
    ```

    The LLM sees seven tools (term structure / skew / ATM greeks shortcuts
    plus the four raw chain tools) and streams its tool calls live.

=== "MCP server (Claude Desktop / claude.ai)"

    Install the MCP extra:

    ```bash
    poetry install -E mcp
    ```

    Then add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

    ```json
    {
      "mcpServers": {
        "voli": {
          "command": "poetry",
          "args": ["run", "voli", "mcp-serve"],
          "cwd": "/absolute/path/to/voli",
          "env": {"POLYGON_API_KEY": "pk_your_key"}
        }
      }
    }
    ```

    Restart Claude Desktop. The Voli tools now appear in the **Available
    Tools** panel and Claude can call them mid-conversation.

=== "Python"

    ```python
    from voli.agent import answer_question

    resp = answer_question("NVDA ATM IV this week vs next week")
    print(resp.summary)
    print(resp.facts["front_iv"], resp.facts["next_iv"])
    ```

## Subcommand summary

| Command | Purpose |
| --- | --- |
| `voli ask "..."` | Rule-based agent. Deterministic, fast, no LLM cost. |
| `voli ask-many --tickers NVDA,SPY,QQQ "..."` | Same prompt across multiple tickers, comparison table. |
| `voli llm-ask "..."` | LLM (Claude / GPT) drives the Voli tools. Streams chain-of-thought. |
| `voli mcp-serve` | MCP server (stdio) for Claude Desktop / claude.ai web. |
| `voli replay <trace_id>` | Re-render a previously stored answer (rule-based or LLM). |
| `voli themes list / preview` | Browse / preview the 12 colour palettes. |

Common flags across the answer commands:

| Flag | Effect |
| --- | --- |
| `--theme NAME` | Pick one of 12 themes (default `bloomberg`). |
| `--cycle-theme` | Rotate to the next theme each invocation. |
| `--no-color` | Disable ANSI (auto when stdout isn't a TTY). |
| `--json` | Machine-readable output. |
| `--trace` | JSONL flight recorder + replay companion. |
| `--skeptic` | Append a `[ SKEPTIC ]` block flagging stale data, wide spreads, etc. |
| `--plot PATH` | Save a category-specific PNG chart (requires `-E plot`). |
| `--data-provider NAME` | Pick a non-default data provider (default `polygon`, or `$VOLI_DATA_PROVIDER`). |

## Optional extras

| Extra | Enables | Install |
| --- | --- | --- |
| `plot` | `--plot` flag (matplotlib charts) | `poetry install -E plot` |
| `anthropic` | Claude provider for `llm-ask` | `poetry install -E anthropic` |
| `openai` | GPT provider for `llm-ask` | `poetry install -E openai` |
| `llm` | Both LLM providers | `poetry install -E llm` |
| `mcp` | `voli mcp-serve` (Claude Desktop / claude.ai) | `poetry install -E mcp` |
| `docs` | `mkdocs serve` for the doc site | `poetry install --with docs` |

## Pluggable providers

Voli is **vendor-agnostic by design** — Polygon ships as the bundled default
but the data-fetch layer sits behind a small Protocol. Same story for the
LLM layer (Anthropic + OpenAI ship in core).

| Layer | Default | Pick a different one with |
| --- | --- | --- |
| Data | `polygon` (Polygon.io) | `voli ask --data-provider NAME` or `$VOLI_DATA_PROVIDER` |
| LLM | auto-detect (Anthropic if key set, else OpenAI) | `voli llm-ask --provider {anthropic,openai}` or `$VOLI_LLM_PROVIDER` |

To **add a new data vendor** (yfinance, Tradier, IBKR, ...) write four
fetcher methods returning Voli domain models, register via a
`voli.data_providers` entry point, ship as `pip install voli-yourvendor`.
Full how-to: [Extending Voli — data providers](docs/extending/data-providers.md).

To **add a new LLM** (Gemini, Grok, local Ollama, ...) implement
`voli.llm.provider.Provider` (mirrors the existing `anthropic_provider.py`
/ `openai_provider.py`). See
[Extending Voli — LLM providers](docs/extending/llm-providers.md).

```bash
# List installed data providers
poetry run python -c "from voli.providers import list_providers; print(list_providers())"
# -> ['polygon']
```

## Daily commands

```bash
# Run all 277 tests (offline, no API key needed)
poetry run python -m pytest

# Lint + format
poetry run ruff check .
poetry run ruff format .

# Eval harness (deterministic, synthetic data)
poetry run python eval/run_eval.py
poetry run python eval/run_eval.py --json

# Doc site (live preview)
poetry install --with docs
poetry run mkdocs serve   # -> http://127.0.0.1:8000
```

## Documentation

Full docs (CLI reference, Python API, examples cookbook for every
subcommand including LLM mode and MCP, architecture, contributing guide)
live in `docs/` as a MkDocs Material site:

```bash
poetry install --with docs
poetry run mkdocs serve
```

## Project structure

| Path | Purpose |
| --- | --- |
| `src/voli/agent/` | Rule-based planner → executor → writer. |
| `src/voli/analytics/` | Pure-function metrics: term structure, skew slope, ATM greeks. |
| `src/voli/providers/` | `DataProvider` Protocol + entry-point registry; bundled Polygon implementation. |
| `src/voli/polygon/` | Polygon HTTP client + response normalisation (used by the bundled provider). |
| `src/voli/tools/` | Cache + meta + trace orchestration around the active provider. |
| `src/voli/llm/` | Provider-agnostic LLM agent (Anthropic + OpenAI). |
| `src/voli/mcp_server.py` | MCP server (stdio) for Claude Desktop / claude.ai. |
| `src/voli/eval/` | Evaluation harness (synthetic registry + runner). |
| `src/voli/cli.py` | Command-line entrypoint. |
| `src/voli/cli_render.py` | Themed ANSI renderer + 10 palettes. |
| `eval/prompts.jsonl` | 20-case regression dataset. |
| `tests/` | pytest suite (277 tests, no live API needed). |
| `docs/` | MkDocs Material doc site. |

## License

Not yet decided. See repository for details.
