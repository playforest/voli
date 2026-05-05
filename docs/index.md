---
title: Home
hide:
  - navigation
---

# Options Query Engine

A Python library and CLI that answers natural-language questions about an
equity option chain — chain slices, IV term structure, skew, basic greeks —
**grounded in Polygon data**, with a runtime guardrail that refuses to invent
numbers.

<div class="grid cards" markdown>

-   :material-flash: __Fast to try__

    ---

    Install with Poetry, drop a Polygon key in `.env`, ask a question.

    [:octicons-arrow-right-24: Installation](getting-started/installation.md)

-   :material-target: __Grounded answers__

    ---

    Every numeric token in a summary must trace back to a tool call or an
    analytics function. The writer raises rather than inventing.

    [:octicons-arrow-right-24: Guardrails](architecture/guardrails.md)

-   :material-palette: __Bloomberg-style CLI__

    ---

    Ten built-in colour themes. Sensible defaults, easy to switch, no emojis.

    [:octicons-arrow-right-24: Themes](cli/themes.md)

-   :material-test-tube: __Reproducible eval__

    ---

    20-case JSONL dataset; per-case checks for tool sequence, table type,
    Facts keys, and numeric metrics within tolerance.

    [:octicons-arrow-right-24: Eval Harness](eval/harness.md)

</div>

## Quickstart

=== "CLI"

    ```bash
    poetry install
    cp .env.example .env  # edit POLYGON_API_KEY
    poetry run oqe ask "NVDA ATM IV this week vs next week"
    ```

=== "Python"

    ```python
    from oqe.agent import answer_question

    resp = answer_question("NVDA ATM IV this week vs next week")
    print(resp.summary)
    print(resp.facts["front_iv"], resp.facts["next_iv"])
    ```

=== "Docker"

    ```bash
    docker compose -f docker/docker-compose.yml run --rm \
      oqe ask "NVDA ATM IV this week vs next week"
    ```

## Sample output

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

## What it answers

| Category | Example prompt |
| --- | --- |
| **Chain lookup** | _"List NVDA calls for 2026-05-16 between 90 and 110."_ |
| **IV term structure** | _"NVDA ATM IV this week vs next week."_ |
| **Skew** | _"What's the skew slope across strikes for TSLA next week?"_ |
| **Greeks** | _"What are the greeks of the NVDA 2026-05-16 100C?"_ |

It refuses anything that requires advice, prediction, or execution
(_"Should I buy NVDA calls?"_) and offers supported rewrites instead.

## Where to go next

- [Installation](getting-started/installation.md) — set up the package
- [Your first query](getting-started/first-query.md) — walkthrough
- [CLI Reference](cli/overview.md) — every flag and subcommand
- [Examples cookbook](examples/term-structure.md) — recipes per category
- [Architecture](architecture/orchestrator.md) — how the pieces fit
