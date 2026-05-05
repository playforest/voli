# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Options Query Engine (OQE) - A Python library for querying options chain data from Polygon.io with built-in caching, reproducibility, and analytics metrics computation.

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

### Package Structure (`src/oqe/`)

**Domain Models** (`models.py`):
- `UnderlyingSnapshot`, `OptionContract`, `OptionQuote`, `OptionGreeks` - Pydantic models with strict validation
- All timestamps must be UTC timezone-aware
- `StrictModel` base class enforces `extra="forbid"` and `frozen=True`

**Polygon Integration** (`polygon/`):
- `client.py` - HTTP client for Polygon.io API with pagination support
- `normalise.py` - Transforms raw Polygon responses into domain models
- `tools.py` - High-level functions: `get_underlying_snapshot_from_options()`, `list_option_contracts_from_options_snapshot()`, `get_option_quotes_from_contract_snapshots()`, `get_option_greeks_from_contract_snapshots()`

**Caching System** (`cache.py`):
- SQLite-based cache with TTL expiration
- Deterministic cache keys from `(tool_name, canonicalized_inputs, asof)`
- Default path: `~/.oqe/cache.sqlite` (override with `OQE_CACHE_PATH`)
- TTLs: 30s for quotes/greeks/underlying snapshots, 6h for contract lists

**Analytics** (`analytics/`):
- `iv_metrics.py` - ATM IV term structure computation with optional spread filtering
- `skew.py` - Volatility skew slope calculation (linear fit across strikes)
- `greeks.py` - ATM greeks extraction for given expiry
- `metrics_bundle.py` - `compute_v1_metrics_bundle()` combines term structure, skew slope, and ATM greeks
- `protocols.py` - Protocol types for duck-typing flexibility

**Run Traces** (`run_trace.py`):
- JSONL "flight recorder" for tool calls
- Default path: `~/.oqe/traces/<trace_id>.jsonl` (override with `OQE_TRACE_DIR`)

### Key Design Patterns

1. **Reproducibility via caching**: Same inputs → same cache key → same outputs (while cache valid)
2. **Spread filtering**: Analytics functions accept `quotes_by_symbol` + `max_relative_spread` to exclude illiquid options
3. **Protocol-based typing**: Analytics use `OptionContractLike`, `OptionQuoteLike`, `OptionGreeksLike` protocols for flexibility
4. **Warnings over exceptions**: Functions return `MetricResult[T]` with value + warnings tuple rather than raising

### Environment Variables

```
POLYGON_API_KEY=<your_key>      # Required for live data
OQE_CACHE_PATH=<path>           # Override default cache location
OQE_TRACE_DIR=<path>            # Override default trace directory
```

## Testing

Tests use a repo-local cache (`.pytest_oqe_cache.sqlite`) via `conftest.py` - automatically cleaned on each pytest run. No live API calls needed for most tests; they use synthetic/mocked data.
