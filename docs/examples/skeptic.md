# Skeptic sub-agent

The skeptic is a small reviewer that runs **after** the writer. It can't
override an answer; it appends a `[ SKEPTIC ]` block of concerns the user
should consider.

## Enable it

=== "CLI"

    ```bash
    poetry run voli ask --skeptic "NVDA ATM IV this week vs next week"
    ```

=== "Python"

    ```python
    from voli.agent import answer_question

    resp = answer_question(
        "NVDA ATM IV this week vs next week",
        skeptic=True,
    )
    for line in resp.skeptic or []:
        print(line)
    ```

=== "Batch"

    ```bash
    poetry run voli ask-many --skeptic --tickers NVDA,SPY,QQQ \
      "ATM IV this week vs next week"
    ```

## What it checks

| Check | Code | Severity | Trigger |
| --- | --- | --- | --- |
| Stale snapshot | `STALE_SNAPSHOT` | warn | Spot snapshot older than 30 minutes. |
| ATM gap | `ATM_GAP` | warn | Chosen ATM strike > 5% away from spot (sparse strike grid). |
| Low contract count | `LOW_CONTRACT_COUNT` | warn | Chain returned fewer than 4 contracts. |
| Missing greeks | `MISSING_GREEKS` | warn | Any of iv / delta / gamma / theta / vega is null on the ATM contract. |
| Wide ATM spread | `WIDE_ATM_SPREAD` | warn | ATM contract bid-ask spread > 20% of mid. |
| Forwarded warnings | `STALE_DATA` / `PARTIAL_DATA` / `NO_RESULTS` / ... | info / warn / critical | Whatever the tool layer flagged is promoted to a structured concern. |

The thresholds live in `voli/agent/skeptic.py` as module constants —
`STALE_SNAPSHOT_MAX_AGE_MINUTES`, `WIDE_SPREAD_RELATIVE_THRESHOLD`,
`LOW_CONTRACT_COUNT_THRESHOLD`, `ATM_GAP_RELATIVE_THRESHOLD`.

## Sample output

```text
[ SKEPTIC ]
WARN      STALE_SNAPSHOT            spot snapshot is 47m old (threshold 30m).
WARN      WIDE_ATM_SPREAD           ATM contract bid/ask = 1.0/2.0 (spread 66.7% of mid)
                                    - mid price may not be tradeable.
WARN      STALE_DATA                tool layer flagged STALE_DATA.
```

Concerns are sorted **critical → warn → info**, then alphabetically by
code, so the most important one is always at the top.

## Why a separate stage?

The writer's `numbers_used` guardrail catches *invented* numbers. The
skeptic catches *suspicious* numbers — quotes that exist but probably
shouldn't be trusted (stale, wide spread, partial data). Different
concern, different stage.

A practical phrasing: the writer answers _"is this number real?"_, the
skeptic answers _"would I trust this number to trade off?"_.

## Programmatic access

```python
from voli.agent.skeptic import review
from voli.agent import answer_question

resp = answer_question("NVDA ATM IV this week vs next week", skeptic=True)
# resp.skeptic is a list of pre-rendered strings (None if --skeptic not used).

# For structured concerns (with .severity, .code, .message), call review() directly:
from voli.eval.synth_market import make_registry
from voli.agent.executor import default_registry
from voli.agent import answer_question

# (rerun the pipeline yourself if you need the raw concerns)
```

## Filter concerns by severity

```python
from voli.agent.skeptic import review, SkepticConcern
from voli.agent import answer_question
from voli.agent.executor import default_registry

# answer_question doesn't expose tool_outputs, so to get raw concerns
# rerun the pipeline manually:
from voli.agent import plan, execute, write
from voli.agent.state import AgentState

state = AgentState(prompt="NVDA ATM IV this week vs next week")
state = plan(state)
state = execute(state, registry=default_registry())
resp = write(state)

concerns = review(resp, tool_outputs=state.tool_outputs)
critical = [c for c in concerns if c.severity == "critical"]
if critical:
    raise RuntimeError(f"Critical data quality issues: {critical}")
```

## See also

- [Multi-ticker batching](batch.md) — the skeptic pairs naturally with batches.
- [Architecture: guardrails](../architecture/guardrails.md) — how the writer's checks differ.
