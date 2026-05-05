# Adding eval cases

The dataset doubles as a regression suite, so add a case for every bug
fix and every new feature.

## Workflow

1. **Pick an `id`.** Sequential `tc_NNN` works fine; use a category prefix
   for readability if you like (`ts_NNN`, `sk_NNN`).
2. **Author the prompt.** Use the same wording you'd want users to write.
3. **Decide the assertions.** Start small (`expected_category`,
   `expected_supported`) and add detail until a regression would catch
   it.
4. **Predict the metrics.** The synthetic surface is documented in
   [Dataset format](dataset-format.md#synthetic-surface-what-to-encode).
   For NVDA call ATM IVs that's `0.30` (front) and `0.35` (next). For a
   new metric, run the agent once against the synthetic registry and
   eyeball the output before encoding it.
5. **Run the harness — and the case should pass on first try if the
   feature works.** If you're TDD-ing a fix, write the case first, watch
   it fail, then make the change.

## Example: add a put-side term-structure case

NVDA front put IV is `0.33`; next put IV is `0.38`.

```jsonl
{"id": "tc_021", "prompt": "NVDA put ATM IV this week vs next week.", "expected_supported": true, "expected_category": "term_structure", "expected_ticker": "NVDA", "expected_tools": ["get_underlying_snapshot", "list_option_contracts", "get_option_greeks"], "expected_table_type": "term_structure", "must_have_facts_keys": ["ticker", "spot", "atm_strike", "front_iv", "next_iv"], "expected_metrics": {"atm_strike": 100.0, "front_iv": 0.33, "next_iv": 0.38}}
```

```bash
# Run just the new case
poetry run python -m pytest tests/test_end_to_end.py::test_case[tc_021] -vv
```

If it passes, the put-side path works.

## Example: assert a refusal

```jsonl
{"id": "tc_022", "prompt": "What's the best NVDA spread for earnings?", "expected_supported": false, "expected_category": "not_supported", "expected_tools": [], "must_contain_in_summary": ["Not supported", "strategy"], "must_have_facts_keys": ["reason"]}
```

The empty `expected_tools` array asserts the agent didn't even call
Polygon — refusals must short-circuit before any tool runs.

## Verifying expected metrics

If you don't know what a metric should be, the synthetic registry makes
it easy to find out:

```python
from oqe.agent import answer_question
from oqe.eval.synth_market import make_registry

reg = make_registry()
resp = answer_question("MSFT ATM IV this week vs next week", registry=reg)
print(resp.facts)
```

Run that, copy the values into your case, done.

## Updating an existing case

Cases are stable; if the agent's behaviour changes intentionally (new
field in Facts, etc.), update the case in the same commit so the diff
makes the contract change visible:

```diff
- "must_have_facts_keys": ["ticker", "spot", "atm_strike"],
+ "must_have_facts_keys": ["ticker", "spot", "atm_strike", "atm_options_symbol_call"],
```

## Don't

- **Don't** add cases that depend on live Polygon data — the harness must
  pass offline.
- **Don't** encode tolerances looser than `1e-3` without a comment
  explaining why; the synthetic surface is exact.
- **Don't** rely on case-execution order. Each row is independent.

## See also

- [Running the harness](harness.md) — how to verify your additions.
- [Dataset format](dataset-format.md) — the JSONL schema.
