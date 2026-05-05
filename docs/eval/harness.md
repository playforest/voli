# Running the harness

`eval/run_eval.py` runs every case in `eval/prompts.jsonl` through the
agent and reports per-case pass/fail. The runner uses the same
`oqe.eval.runner.evaluate_case` that the pytest version (`tests/test_end_to_end.py`)
calls — they can never disagree.

## Quickstart

```bash
poetry run python eval/run_eval.py
```

```text
================================================================================
 OQE EVAL | 20 cases | 20 passed | 0 failed
================================================================================
[ RESULTS ]
PASS  tc_001    term_structure    NVDA ATM IV this week vs next week.
PASS  tc_002    term_structure    Compare ATM IV for SPY front week vs next ...
... (18 more rows) ...

[ BY CATEGORY ]
chain                 6/6
greeks                3/3
not_supported         4/4
skew                  3/3
term_structure        4/4
================================================================================
```

Exit code `0` if every case passes, `1` otherwise.

## Modes

=== "Themed report (default)"

    ```bash
    poetry run python eval/run_eval.py
    ```

=== "JSON for CI"

    ```bash
    poetry run python eval/run_eval.py --json
    ```

    ```json
    {
      "by_category": {
        "chain":          {"passed": 6, "total": 6},
        "greeks":         {"passed": 3, "total": 3},
        "not_supported":  {"passed": 4, "total": 4},
        "skew":           {"passed": 3, "total": 3},
        "term_structure": {"passed": 4, "total": 4}
      },
      "cases": [
        {"id": "tc_001", "passed": true, "failures": [], ...},
        ...
      ],
      "failed": 0,
      "passed": 20,
      "total": 20
    }
    ```

=== "Different theme"

    ```bash
    poetry run python eval/run_eval.py --theme matrix
    ```

=== "Pytest"

    ```bash
    poetry run python -m pytest tests/test_end_to_end.py -v
    ```

    Per-case parametrised failures, IDE-clickable.

## Custom dataset

```bash
poetry run python eval/run_eval.py --dataset path/to/my_cases.jsonl
```

Same JSONL schema (see [Dataset format](dataset-format.md)).

## What gets checked per case

| Check | Source |
| --- | --- |
| Case ran without raising | always |
| `supported` flag matches | `expected_supported` |
| Category matches | `expected_category` |
| Ticker matches | `expected_ticker` |
| Tool sequence matches **exactly** | `expected_tools` |
| Table type matches | `expected_table_type` |
| Each Facts key present | `must_have_facts_keys` |
| Each substring present in summary | `must_contain_in_summary` |
| Each numeric metric within tolerance | `expected_metrics`, `metrics_tolerance` |

Skip a check by omitting the corresponding field.

## Sample failure output

If you break the writer (drop `atm_strike` from term-structure facts):

```text
FAIL  tc_001    term_structure    NVDA ATM IV this week vs next week.
        -> facts.atm_strike: missing
        -> metric:atm_strike: missing (expected 100.0)
FAIL  tc_002    term_structure    Compare ATM IV for SPY front week vs ...
        -> facts.atm_strike: missing
        -> metric:atm_strike: missing (expected 500.0)
...
```

The harness reports four cases failing rather than one summary line — you
see exactly which fields and which prompts.

## When to run

| Trigger | Recommended |
| --- | --- |
| Any agent / analytics / writer change | run before pushing |
| Polygon tool layer change | run with `--theme matrix` to glance at the report |
| New prompt category | add cases first, run, watch them fail, fix until green |
| CI | `poetry run python eval/run_eval.py --json` and gate on exit code |

## See also

- [Dataset format](dataset-format.md) — every JSONL field.
- [Adding cases](adding-cases.md) — workflow for new test cases.
