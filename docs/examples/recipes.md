# Recipes

Patterns for using OQE in real workflows.

## Compare ATM IV across a watchlist

Print front-vs-next IV for a list of tickers in one pass.

```python
from oqe.agent import answer_question

WATCHLIST = ["NVDA", "SPY", "QQQ", "AAPL", "TSLA"]

print(f"{'TICKER':6}  {'FRONT':>9}  {'NEXT':>9}  {'DIFF':>9}")
for t in WATCHLIST:
    resp = answer_question(f"{t} ATM IV this week vs next week")
    f = resp.facts.get("front_iv")
    n = resp.facts.get("next_iv")
    if f is None or n is None:
        print(f"{t:6}  (no data)")
        continue
    print(f"{t:6}  {f:>9.4f}  {n:>9.4f}  {n - f:>+9.4f}")
```

```text
TICKER     FRONT      NEXT       DIFF
NVDA      0.3318    0.3457    +0.0139
SPY       0.1543    0.1612    +0.0069
QQQ       0.1820    0.1935    +0.0115
AAPL      0.2210    0.2304    +0.0094
TSLA      0.4515    0.4620    +0.0105
```

## Save an audit trail per query

```bash
poetry run oqe ask --trace "NVDA ATM IV this week vs next week"
```

```text
... output ...
trace_id: 20260505T130904Z_a1b2c3d4
```

```bash
cat ~/.oqe/traces/20260505T130904Z_a1b2c3d4.jsonl
```

```jsonl
{"event": "trace_start", ...}
{"event": "tool_call", "tool": "get_underlying_snapshot", ...}
{"event": "tool_call", "tool": "list_option_contracts", ...}
{"event": "tool_call", "tool": "get_option_greeks", ...}
{"event": "trace_end", ...}
```

Useful for after-the-fact debugging or reproducibility evidence.

## Run a one-shot scheduled pull

In a cron job (default theme is bloomberg; we force JSON for parsing):

```bash
*/15 * 9-16 * 1-5 \
  /usr/local/bin/poetry run --directory /opt/oqe \
  oqe ask --json "NVDA ATM IV this week vs next week" \
  >> /var/log/oqe-nvda-iv.jsonl
```

Each line is one JSON object with timestamp + IV — easy to load into
pandas / DuckDB / a TSDB later.

## Compose with jq for shell scripting

```bash
# Just the front IV
poetry run oqe ask --json "NVDA ATM IV this week vs next week" \
  | jq -r '.facts.front_iv'

# All numbers used (auditable list)
poetry run oqe ask --json "NVDA ATM IV this week vs next week" \
  | jq '.numbers_used'

# Compact one-line summary
poetry run oqe ask --json "NVDA ATM IV this week vs next week" \
  | jq -r '"\(.facts.ticker) front=\(.facts.front_iv) next=\(.facts.next_iv)"'
```

## Run an offline regression check

Before opening a PR:

```bash
# Lint
poetry run ruff check .
poetry run ruff format .

# Tests (170+ in <0.5s)
poetry run python -m pytest -q

# Eval harness (synthetic, deterministic)
poetry run python eval/run_eval.py --no-color
```

If all three are green, the agent's contract hasn't regressed.

## Build a custom registry (offline tests)

For internal tooling that wants reproducible outputs without Polygon:

```python
from oqe.agent import answer_question
from oqe.eval.synth_market import make_registry

reg = make_registry()
resp = answer_question("NVDA ATM IV this week vs next week", registry=reg)
assert resp.facts["front_iv"] == 0.30
```

The synthetic surface is documented in
[Adding eval cases](../eval/adding-cases.md).

## Cycle themes during a demo

```bash
for prompt in \
  "NVDA ATM IV this week" \
  "Show NVDA IV skew next Friday" \
  "What are the greeks of the NVDA 2026-05-16 100C?" \
  "Show NVDA options for 2026-05-16"
do
  poetry run oqe ask --cycle-theme "$prompt"
done
```

Four queries, four different themes (bloomberg → bloomberg_classic →
matrix → amber_crt by default).

## See also

- [CLI overview](../cli/overview.md) — every flag.
- [Python API](../python-api/answer-question.md) — programmatic surface.
