# Options Query Engine (OQE)

> A Python library + CLI that answers natural-language questions about an
> equity option chain — chain slices, IV term structure, skew, greeks —
> grounded in Polygon data, with a "no invented numbers" guarantee.

```text
================================================================================
 OQE | TICKER: NVDA | CATEGORY: TERM_STRUCTURE | OK
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

## Why OQE?

- **Grounded.** Every numeric claim in the answer must come from a tool call
  or a centralised analytics function — the writer enforces a runtime
  guardrail and refuses to emit invented numbers.
- **Deterministic.** A heuristic planner produces the same plan for the same
  prompt; analytics are pure functions over the chain snapshot. Same prompt
  + same cache window = same answer.
- **Bloomberg-style CLI.** Ten bundled colour themes; defaults to a
  Bloomberg-Terminal-inspired orange/amber on black.
- **Reproducible eval.** A 20-case JSONL dataset and a runner that scores
  per-case checks (tool sequence, table type, Facts keys, numeric metrics)
  and exits non-zero on any regression.

## Quickstart

```bash
# Install
poetry install

# Add your Polygon key
cp .env.example .env
echo "POLYGON_API_KEY=pk_xxx" > .env

# Ask a question
poetry run oqe ask "NVDA ATM IV this week vs next week"

# Try a different theme
poetry run oqe ask --theme matrix "Show NVDA IV skew next Friday"

# See all themes
poetry run oqe themes preview --all

# Run the eval harness
poetry run python eval/run_eval.py
```

## Common commands

```bash
# Run all tests
poetry run python -m pytest

# Run linter / formatter
poetry run ruff check .
poetry run ruff format .

# Eval (themed report)
poetry run python eval/run_eval.py

# Eval (machine-readable)
poetry run python eval/run_eval.py --json
```

## Documentation

Full docs (CLI reference, Python API, examples cookbook, architecture,
contributing) live in `docs/` as MkDocs Material pages:

```bash
poetry install --with docs
poetry run mkdocs serve
# -> open http://127.0.0.1:8000
```

## Project structure

| Path | Purpose |
| --- | --- |
| `src/oqe/agent/` | Planner -> Executor -> Writer orchestrator. |
| `src/oqe/analytics/` | Pure-function metrics: term structure, skew slope, ATM greeks. |
| `src/oqe/polygon/` | HTTP client + response normalisation. |
| `src/oqe/tools/` | High-level tool wrappers used by the executor. |
| `src/oqe/eval/` | Evaluation harness (synthetic registry + runner). |
| `src/oqe/cli.py` | Command-line entrypoint. |
| `src/oqe/cli_render.py` | Themed ANSI renderer. |
| `eval/prompts.jsonl` | 20-case regression dataset. |
| `tests/` | pytest suite (170+ tests, no live API needed). |
| `docs/` | MkDocs Material doc site. |

## License

Not yet decided. See repository for details.
