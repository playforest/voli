# Concepts

A short tour of what OQE does, what it refuses, and the few terms used
across the rest of these docs.

## What it answers (v1)

OQE classifies every prompt into one of four supported categories or one
refusal bucket.

| Category | Example | Output table |
| --- | --- | --- |
| **Chain lookup** | _"List NVDA calls for 2026-05-16 between 90 and 110."_ | `chain_slice` |
| **IV term structure** | _"NVDA ATM IV this week vs next week."_ | `term_structure` |
| **Skew** | _"What's the skew slope across strikes for TSLA next week?"_ | `skew` |
| **Greeks** | _"What are the greeks of the NVDA 2026-05-16 100C?"_ | `greeks` |
| **Not supported** | _"Should I buy NVDA calls?"_ | `none` (with rewrites) |

## What it refuses

Anything that needs advice, prediction, execution, news causality, or
portfolio reasoning. Refusals come back labelled, with one to three
**supported rewrites**:

```text
[ SUMMARY ]
Not supported in scope: this question falls under 'execution'. I can return
data, not recommendations.

[ REASON ]
execution

[ TRY INSTEAD ]
> Show ATM call and put for NVDA next week with bid/ask/mid.
```

## Pipeline

Every query walks the same four stages.

``` mermaid
flowchart LR
  A[prompt] --> B[planner]
  B -->|Intent + Plan| C[executor]
  C -->|tool outputs| D[analytics]
  D -->|metrics| E[writer]
  E --> F[AnswerResponse]
```

- **Planner** — regex/keyword rules, no LLM. Picks the category and the
  exact tool sequence.
- **Executor** — runs each `PlanStep` against a `ToolRegistry` (Polygon in
  prod; synthetic in tests). Resolves late-bound inputs (e.g. quotes need
  the contracts list).
- **Analytics** — pure functions in `oqe.analytics` compute metrics
  (term structure, skew slope, ATM greeks).
- **Writer** — renders summary + table + Facts. Enforces the
  no-invented-numbers guardrail.

See [Orchestrator flow](../architecture/orchestrator.md) for the full
diagram.

## Guardrails

The writer enforces two contract guarantees on every supported answer:

1. **No invented numbers.** Every numeric token in `summary` must match a
   value in `numbers_used` within tolerance. The writer raises
   `GuardrailViolation` rather than emit a misleading answer.
2. **Facts section is mandatory.** Every supported response carries a
   `facts` dict with the spot price (value + ts + source), expiries used,
   right filter, and the analytics flags.

## Determinism

- The planner is rule-based, so the same prompt always produces the same
  plan.
- The cache (SQLite) keys on `(tool_name, canonicalized_inputs, asof)` so
  the same prompt + same cache window returns the same data.
- Analytics functions are pure — no I/O, no globals.

If you want strictly reproducible eval runs, point the harness at the
synthetic registry (default in tests + `eval/run_eval.py`).

## Glossary

| Term | Definition |
| --- | --- |
| **ATM** | At-the-money. Strike closest to spot. |
| **Front / next expiry** | Earliest two listed expiries for a ticker, sorted ascending. |
| **Mid** | `(bid + ask) / 2` when both are available; otherwise `last`; otherwise `null`. |
| **Skew slope** | OLS slope of IV vs strike across the front expiry. |
| **Refusal rewrite** | A `Supported (v1)` prompt the agent suggests after refusing the original. |
| **Trace ID** | Unique ID for one CLI invocation; appears at the bottom of the output and in `~/.oqe/traces/<id>.jsonl` when `--trace` is set. |

## Next

- [CLI overview](../cli/overview.md) — every flag and subcommand
- [Architecture](../architecture/orchestrator.md) — internals
- [Examples](../examples/term-structure.md) — recipes per category
