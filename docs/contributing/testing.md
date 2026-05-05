# Testing

The test suite is fast (170+ tests in under half a second), offline by
default, and structured so failures point at exactly one thing.

## Layers

| Layer | What it covers | Example file |
| --- | --- | --- |
| **Unit** | Pure functions: analytics, models, normalisation | `tests/test_analytics_metrics.py`, `tests/test_polygon_normalise.py` |
| **Tool** | Tool wrappers + cache + trace | `tests/test_tool_cache_quotes.py`, `tests/test_tool_trace_underlying.py` |
| **Agent** | Planner classification, writer guardrails | `tests/test_agent_planner.py`, `tests/test_agent_writer.py` |
| **End-to-end** | Full prompt → response with stubbed registry | `tests/test_agent_end_to_end.py`, `tests/test_end_to_end.py` (eval-driven) |
| **CLI** | argparse, theming, JSON mode, error rendering | `tests/test_cli.py`, `tests/test_cli_render.py`, `tests/test_themes.py` |

## Conventions

- **No live API calls** in any test. The synthetic registry from
  `oqe.eval.synth_market` is the canonical fake. Older test files have
  inline stubs with the same shape — both are fine.
- **`tests/conftest.py`** sets `OQE_CACHE_PATH` to a repo-local SQLite
  file (`.pytest_oqe_cache.sqlite`) and deletes it at startup. Tests
  never share a cache.
- **No `print` debugging in committed tests.** Use `pytest -vv -s` if
  you need to see output during a one-off debug session.

## Running

```bash
# Full suite
poetry run python -m pytest

# Quiet mode (default in CI)
poetry run python -m pytest -q

# A single file
poetry run python -m pytest tests/test_agent_writer.py -vv

# A single test
poetry run python -m pytest tests/test_agent_writer.py::test_finalize_rejects_invented_number -vv

# Eval-driven cases only
poetry run python -m pytest tests/test_end_to_end.py -v
```

## Adding a test

For a bug fix, write the failing test first, then make the change. For a
new feature, prefer the smallest layer that proves it works:

| Change | Where to add a test |
| --- | --- |
| New analytics function | `tests/test_analytics_metrics.py` (or a new file in `tests/`) |
| Planner classifier change | `tests/test_agent_planner.py` |
| Writer/render change | `tests/test_agent_writer.py` (guardrail) **and** an eval case |
| New CLI flag | `tests/test_cli.py` (text mode) + `tests/test_themes.py` if it touches theming |
| Expected behaviour over a real prompt | a row in `eval/prompts.jsonl` (covered automatically by `tests/test_end_to_end.py`) |

## Sabotage check

To convince yourself the eval is meaningful, sabotage something locally:

```python
# In oqe/agent/writer.py, comment out a line that adds atm_strike to facts.
poetry run python eval/run_eval.py
# Expect: 4 failed cases with `facts.atm_strike: missing`.
```

Then revert. The harness should report 20 / 20 again.

## Coverage

Not currently tracked. If you want a number: `poetry run python -m pytest
--cov=oqe`. The eval harness covers the agent end-to-end path; analytics
and tools have their own targeted tests.

## CI

Not yet wired (no `.github/workflows/`). Recommended baseline:

```yaml
# .github/workflows/ci.yml (suggested)
- run: poetry install --with dev
- run: poetry run ruff check .
- run: poetry run python -m pytest -q
- run: poetry run python eval/run_eval.py --json
```

## See also

- [Setup](setup.md) — install + daily commands.
- [Eval harness](../eval/harness.md) — the JSONL-driven regression suite.
