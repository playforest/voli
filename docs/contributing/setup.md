# Setup

Local development uses Poetry, ruff, and pytest. No system-level deps
beyond Python 3.11.

## Bootstrap

```bash
git clone https://github.com/playforest/options-query-agent
cd options-query-agent
poetry install --with dev,docs
```

That installs:

- runtime deps (httpx, pydantic, python-dotenv, pyyaml)
- dev deps (pytest, ipykernel, jupyter)
- docs deps (mkdocs, mkdocs-material, pymdown-extensions)

## Pre-commit hooks

```bash
poetry run pre-commit install
```

Now `git commit` runs `ruff check` + `ruff format` automatically.

## Daily commands

```bash
# Run every test (170+ in <0.5s)
poetry run python -m pytest

# Run one file or one test
poetry run python -m pytest tests/test_agent_writer.py -vv
poetry run python -m pytest tests/test_agent_writer.py::test_finalize_rejects_invented_number -vv

# Lint
poetry run ruff check .
poetry run ruff check . --fix

# Format
poetry run ruff format .

# Eval harness (offline, no API key needed)
poetry run python eval/run_eval.py
```

## Working on docs

```bash
# Live preview (auto-reloads on save)
poetry run mkdocs serve
# -> http://127.0.0.1:8000

# Static build into ./site/
poetry run mkdocs build
```

## Working with live Polygon data

Optional but useful for chain / greeks development.

```bash
cp .env.example .env
# Edit .env so POLYGON_API_KEY=pk_...
poetry run oqe ask "NVDA ATM IV this week vs next week"
```

`POLYGON_HTTP_DEBUG=1` prints every HTTP request on stderr — useful when
something hangs or returns unexpectedly.

## Project layout

| Path | Purpose |
| --- | --- |
| `src/oqe/agent/` | planner / executor / writer / state |
| `src/oqe/analytics/` | term structure, skew, greeks, metrics bundle |
| `src/oqe/polygon/` | HTTP client + response normalisation |
| `src/oqe/tools/` | high-level Polygon-backed tool functions |
| `src/oqe/eval/` | synthetic registry + eval runner |
| `src/oqe/cli.py` | CLI entrypoint |
| `src/oqe/cli_render.py` | themed ANSI renderer + 10 palettes |
| `src/oqe/config.py` | YAML config loader |
| `src/oqe/logging.py` | structured logging setup |
| `tests/` | pytest suite |
| `eval/prompts.jsonl` | regression dataset |
| `eval/run_eval.py` | top-level eval shell |
| `docs/` | MkDocs Material docs (this site) |

## See also

- [Testing](testing.md) — what runs where, fixtures, conventions.
- [Releasing](release.md) — versioning + tag flow.
