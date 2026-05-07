# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Voli - A Python library for querying options chain data with built-in caching, reproducibility, and analytics metrics computation. Vendor-agnostic: bundled with a Polygon.io data provider, but the data-fetch layer sits behind a `DataProvider` Protocol so forks can plug in yfinance / Tradier / IBKR / etc. via a `voli.data_providers` entry point. Same shape on the LLM side (Anthropic + OpenAI bundled).

## Commands

```bash
# Install dependencies
poetry install

# Run all tests
poetry run python -m pytest

# Run single test file
poetry run python -m pytest tests/test_cache.py -vv

# Run single test function
poetry run python -m pytest tests/test_cache.py::test_ttl_expiry_deletes_entry -vv

# Show test output
poetry run python -m pytest -vv -s

# Linting and formatting
poetry run ruff check .
poetry run ruff check . --fix
poetry run ruff format .

# Run pre-commit hooks
poetry run pre-commit run --all-files
```

## Architecture

### Package Structure (`src/voli/`)

**Domain Models** (`models.py`):
- `UnderlyingSnapshot`, `OptionContract`, `OptionQuote`, `OptionGreeks` - Pydantic models with strict validation
- All timestamps must be UTC timezone-aware
- `StrictModel` base class enforces `extra="forbid"` and `frozen=True`

**Data Provider Layer** (`providers/`):
- `__init__.py` - `DataProvider` Protocol + registry + entry-point discovery (group `voli.data_providers`). `register()`, `get()`, `set_active()`, `get_active()`, `list_providers()`. Polygon is pre-registered; third-party providers are loaded lazily.
- `polygon.py` - `PolygonProvider`, the bundled default. Implements all four `fetch_*` methods plus the optional `fetch_option_chain_bulk`.
- Adapter authors implement four small fetcher methods returning Voli domain models. Voli core handles cache, meta, trace, and the guardrail.

**Polygon HTTP** (`polygon/`):
- `client.py` - HTTP client for Polygon.io API with pagination support (used by the bundled provider)
- `normalise.py` - Transforms raw Polygon responses into domain models
- `tools.py` - Lower-level helpers used by the provider

**Caching System** (`cache.py`):
- SQLite-based cache with TTL expiration
- Deterministic cache keys from `(tool_name, canonicalized_inputs, asof)`
- Default path: `~/.voli/cache.sqlite` (override with `VOLI_CACHE_PATH`)
- TTLs: 30s for quotes/greeks/underlying snapshots, 6h for contract lists

**Analytics** (`analytics/`):
- `iv_metrics.py` - ATM IV term structure computation with optional spread filtering
- `skew.py` - Volatility skew slope calculation (linear fit across strikes)
- `greeks.py` - ATM greeks extraction for given expiry
- `metrics_bundle.py` - `compute_v1_metrics_bundle()` combines term structure, skew slope, and ATM greeks
- `protocols.py` - Protocol types for duck-typing flexibility

**Run Traces** (`run_trace.py`):
- JSONL "flight recorder" for tool calls
- Default path: `~/.voli/traces/<trace_id>.jsonl` (override with `VOLI_TRACE_DIR`)

**Rule-based Agent** (`agent/`):
- `planner.py` / `executor.py` / `writer.py` / `state.py` / `skeptic.py` / `batch.py`
- `answer_question(prompt, ...)` is the public entrypoint
- Writer enforces "no invented numbers" guardrail; raises `GuardrailViolation`

**LLM-driven Agent** (`llm/`):
- Provider-agnostic: `provider.py` + `anthropic_provider.py` + `openai_provider.py`
- `tools.py` exposes the 4 raw Polygon tools as `ToolDef`; `analytics_tools.py` adds the 3 analytics shortcuts (term structure / skew / ATM greeks)
- `agent.py` -> `llm_ask(prompt, provider, tools, ...)` drives the loop
- `skeptic.py` + `replay.py` mirror the rule-based equivalents for LLM mode

**MCP Server** (`mcp_server.py`):
- Exposes the same `build_default_tools()` over MCP stdio
- Wired into Claude Desktop via `claude_desktop_config.json`
- Lazy-imports `mcp` SDK; `voli mcp-serve` is the CLI entrypoint

**CLI** (`cli.py` + `cli_render.py`):
- Subcommands: `ask`, `ask-many`, `llm-ask`, `mcp-serve`, `replay`, `themes`
- 12 Bloomberg-style colour themes; `--theme NAME` / `--cycle-theme` / `--no-color`
- `--data-provider NAME` flag on `ask` / `ask-many` / `llm-ask` / `mcp-serve` (default `polygon`, env `$VOLI_DATA_PROVIDER`)
- `cli_render.py` renders all output through one themed pipeline

### Key Design Patterns

1. **Reproducibility via caching**: Same inputs → same cache key → same outputs (while cache valid)
2. **Spread filtering**: Analytics functions accept `quotes_by_symbol` + `max_relative_spread` to exclude illiquid options
3. **Protocol-based typing**: Analytics use `OptionContractLike`, `OptionQuoteLike`, `OptionGreeksLike` protocols for flexibility
4. **Warnings over exceptions**: Functions return `MetricResult[T]` with value + warnings tuple rather than raising

### Environment Variables

```
POLYGON_API_KEY=<your_key>       # Required when active data provider is polygon (the default)
ANTHROPIC_API_KEY=<your_key>     # Required for `voli llm-ask --provider anthropic` + MCP via Claude
OPENAI_API_KEY=<your_key>        # Required for `voli llm-ask --provider openai`
VOLI_DATA_PROVIDER=<name>        # Active data provider name (default: polygon)
VOLI_LLM_PROVIDER=<name>         # Default LLM provider when --provider not passed
VOLI_LLM_MODEL=<name>            # Default model name when --model not passed
VOLI_CACHE_PATH=<path>           # Override default cache location
VOLI_TRACE_DIR=<path>            # Override default trace directory
VOLI_THEME=<name>                # Default colour theme (default: bloomberg)
```

### Optional Extras

```bash
poetry install -E plot          # matplotlib for `--plot PATH`
poetry install -E anthropic     # Claude provider for llm-ask + MCP
poetry install -E openai        # GPT provider for llm-ask
poetry install -E llm           # both LLM providers
poetry install -E mcp           # `voli mcp-serve`
poetry install --with docs      # mkdocs site
```

## Testing

Tests use a repo-local cache (`.pytest_voli_cache.sqlite`) via `conftest.py`, automatically cleaned on each pytest run. No live API calls needed for any tests; they use synthetic/mocked data. Current count: 282 tests. Tests that exercise the Polygon HTTP layer monkey-patch `voli.providers.polygon.PolygonClient` (the runtime call site); older fixtures patching `voli.tools.polygon_tools.PolygonClient` no longer take effect.

## Documentation Maintenance

Treat doc updates as part of "feature done", not a separate task. When
adding or changing user-facing behaviour:

* Update `README.md` if quickstart, env vars, subcommands, or extras change.
* Update `docs/index.md` if hero cards / quickstart tabs / subcommand map need it.
* Update `docs/getting-started/installation.md` for new env vars or extras.
* Update `docs/cli/overview.md` for new flags / subcommands.
* Add or update the relevant `docs/examples/<feature>.md` page.
* Run `poetry run mkdocs build --strict` and verify zero warnings before pushing.

Bundle the doc commit in the same push as the feature commit so a reader
of git history sees feature + docs land together. Never ship a feature
that updates code/tests without touching docs unless the change is
internal-only (refactor, dep bump, lint fix).
