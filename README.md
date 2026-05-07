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

## See it in action

Five questions. Five different output shapes. All grounded — no fabricated numbers.

### 1. ATM IV across two expiries

```bash
voli ask "NVDA ATM IV this week vs next week"
```

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
SPOT          value=199.8450  ts=2026-05-05T13:09:04Z  source=polygon
ATM_STRIKE    200
FRONT_IV      0.3318
NEXT_IV       0.3457
================================================================================
```

Every number in the summary traces back to a `[ FACTS ]` row — that's the
no-invented-numbers guardrail. Try editing the writer to make up a number;
it raises.

### 2. Skew slope across strikes

```bash
voli ask "Show NVDA IV skew for next Friday"
```

```text
[ SUMMARY ]
NVDA skew slope: OLS slope -0.0021 (IV vs strike) at front expiry 2026-05-16.

[ SKEW ]
FRONT_EXPIRY  |  ATM_STRIKE  |    SLOPE
----------------------------------------
2026-05-16    |         200  |  -0.0021
```

Negative slope = downside protection bid (typical for index ETFs). Switch
ticker to `TSLA` and watch the slope deepen.

### 3. Compare a watchlist in one call

```bash
voli ask-many --tickers NVDA,SPY,QQQ "ATM IV this week vs next week"
```

```text
[ TERM STRUCTURE COMPARISON ]
TICKER  |  ATM_STRIKE  |  FRONT_IV  |  NEXT_IV  |    DIFF  |  STATUS
--------------------------------------------------------------------
NVDA    |         200  |    0.3318  |   0.3457  |  0.0139  |  OK
SPY     |         500  |    0.1820  |   0.1935  |  0.0115  |  OK
QQQ     |         400  |    0.2102  |   0.2240  |  0.0138  |  OK
```

Same prompt, three tickers, one comparison table. The renderer auto-picks
columns based on the dominant question category.

### 4. Free-form question with an LLM driving the tools

```bash
voli llm-ask "How does NVDA's IV term structure compare to QQQ's?"
```

```text
[ TOOL CALL ] compute_atm_iv_term_structure(ticker=NVDA)
[ TOOL OK   (polygon) ] {"front_iv": 0.3318, "next_iv": 0.3457, ...}

[ TOOL CALL ] compute_atm_iv_term_structure(ticker=QQQ)
[ TOOL OK   (cache) ]   {"front_iv": 0.2102, "next_iv": 0.2240, ...}

[ ANSWER ]
NVDA's near-term ATM IV is roughly 60% higher than QQQ's: 33.18% vs 21.02%
for the 2026-05-09 expiry, and 34.57% vs 22.40% for 2026-05-16. Both names
show a similar ~1.4-point premium front-to-next, but as a percentage that's
mild for NVDA (4.2%) and slightly elevated for QQQ (6.6%) — the relative
term-structure premium signal points to QQQ, not NVDA.
```

Live tool-call streaming. Each `(polygon)` / `(cache)` marker tells you
whether the data was fresh or served from the local TTL cache.

### 5. Swap data vendor with one flag

```bash
pip install -e ./examples/yfinance_provider/
voli ask --data-provider yfinance "list NVDA calls for the nearest expiry"
```

```text
[ FACTS ]
SPOT             value=207.8300  ts=2026-05-07T10:37:31Z  source=yfinance
CONTRACTS_COUNT  500
EXPIRIES_USED    2026-05-08, 2026-05-11, 2026-05-13, 2026-05-15, 2026-05-18
```

Same pipeline, different vendor — `source=yfinance` instead of
`source=polygon`. A fork ships a new vendor by writing four small fetcher
methods. See [Extending Voli](docs/extending/data-providers.md).

### And in Claude Desktop / claude.ai web

```bash
voli mcp-serve                # exposes the same tools over MCP stdio
```

Wire the one-liner into Claude Desktop's `claude_desktop_config.json` and
ask options questions in chat — Claude calls the Voli tools mid-conversation
and answers grounded in the same Polygon data the CLI uses.

## Why Voli?

- **Grounded.** Every numeric token in the summary must come from a tool
  call or a centralised analytics function. The writer raises rather than
  inventing.
- **Deterministic + LLM-driven side by side.** The rule-based path gives
  the same answer for the same prompt + cache window. The LLM path drives
  the same tools for free-form questions.
- **Pluggable.** Data providers (Polygon, yfinance, …) and LLM providers
  (Anthropic, OpenAI, …) sit behind small Protocols. A fork ships a new
  vendor by writing four fetchers + an entry-point line.
- **Reproducible.** SQLite TTL cache, JSONL run-trace, replay mode — same
  prompt + same cache window = same answer, every time.
- **Reproducible eval.** 20-case JSONL dataset; the runner exits non-zero
  on any regression in tool sequence, table type, Facts keys, or numeric
  metrics.

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

# Optional — only needed for `voli llm-ask` and the MCP server
ANTHROPIC_API_KEY=sk-ant-your_anthropic_key   # for Claude
OPENAI_API_KEY=sk-your_openai_key             # for GPT
```

The CLI loads `.env` automatically on startup. Anything in your shell
environment wins over `.env`.

### 3. Run the entry point you want

**Rule-based CLI** — always available:

```bash
poetry run voli ask "NVDA ATM IV this week vs next week"
```

**LLM-driven CLI** — install a provider extra first:

```bash
poetry install -E anthropic                 # or -E openai, or -E llm for both
poetry run voli llm-ask "How does NVDA compare to QQQ?"
```

**MCP server** for Claude Desktop / claude.ai:

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

Restart Claude Desktop — the Voli tools appear in the Available Tools panel.

**Direct Python**:

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

A few combinations worth keeping handy:

```bash
# Cycle the theme on every call (great for screenshots)
voli ask --cycle-theme "Show NVDA IV skew next Friday"

# JSON for piping into jq / scripts
voli ask --json "NVDA ATM IV this week vs next week" \
  | jq '{front: .facts.front_iv, next: .facts.next_iv}'

# Open a JSONL trace + replay companion (offline rendering later)
voli ask --trace "Show greeks of the NVDA 2026-05-16 200C"
voli replay 20260507T103717Z_a1b2c3d4
```

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

To **add a new data vendor** (yfinance, Tradier, IBKR, …) write four
fetcher methods returning Voli domain models, register via a
`voli.data_providers` entry point, ship as `pip install voli-yourvendor`.
A complete working example lives in
[`examples/yfinance_provider/`](examples/yfinance_provider/) — read it
end-to-end. Full how-to:
[Extending Voli — data providers](docs/extending/data-providers.md).

To **add a new LLM** (Gemini, Grok, local Ollama, …) implement
`voli.llm.provider.LLMProvider` (mirrors the existing `anthropic_provider.py`
/ `openai_provider.py`). See
[Extending Voli — LLM providers](docs/extending/llm-providers.md).

```bash
# List installed data providers
poetry run python -c "from voli.providers import list_providers; print(list_providers())"
# -> ['polygon', 'yfinance']    # after pip install -e ./examples/yfinance_provider/
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
subcommand including LLM mode and MCP, architecture, how-to-extend
guides, contributing guide) live in `docs/` as a MkDocs Material site:

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
| `examples/yfinance_provider/` | Reference second `DataProvider` implementation (yfinance). |
| `eval/prompts.jsonl` | 20-case regression dataset. |
| `tests/` | pytest suite (277 tests, no live API needed). |
| `docs/` | MkDocs Material doc site. |

## License

Not yet decided. See repository for details.
