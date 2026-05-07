# Multi-ticker batching

`voli ask-many` runs the same prompt against a list of tickers and renders a
single comparison table. Each ticker goes through the regular
planner → executor → writer pipeline; the renderer just lays them out
side-by-side.

## "ATM IV across a watchlist"

```bash
poetry run voli ask-many --tickers NVDA,SPY,QQQ,AAPL,TSLA \
  "ATM IV this week vs next week"
```

```text
================================================================================
 VOLI BATCH | CATEGORY: TERM_STRUCTURE | TICKERS: 5 | OK: 5
================================================================================
[ PROMPT ]
ATM IV this week vs next week

[ TERM STRUCTURE COMPARISON ]
TICKER  |  ATM_STRIKE  |  FRONT_IV  |  NEXT_IV  |    DIFF  |  STATUS
--------------------------------------------------------------------
NVDA    |         100  |    0.3000  |   0.3500  |  0.0500  |  OK
SPY     |         500  |    0.3000  |   0.3500  |  0.0500  |  OK
QQQ     |         400  |    0.3000  |   0.3500  |  0.0500  |  OK
AAPL    |         200  |    0.3000  |   0.3500  |  0.0500  |  OK
TSLA    |         250  |    0.3000  |   0.3500  |  0.0500  |  OK
================================================================================
```

## How prompts work in batches

The prompt is **the same for every ticker**. Each ticker is passed as
`ticker_default` — the planner only uses it when the prompt itself doesn't
contain a ticker. So:

- ✅ `"ATM IV this week vs next week"` — generic, ticker_default wins each row.
- ❌ `"NVDA ATM IV this week"` — planner extracts NVDA every time, the
  `--tickers` list is ignored.

When in doubt, drop the ticker from the prompt.

## Per-category columns

The renderer picks columns based on the dominant category across rows.

| Category | Columns |
| --- | --- |
| `term_structure` | ticker · atm_strike · front_iv · next_iv · diff · status |
| `skew` | ticker · front_expiry · atm_strike · skew_slope · status |
| `greeks` | ticker · strike · iv · delta · gamma · theta · vega · status |
| `chain` | ticker · spot · contracts_count · expiries_used · status |

## Examples

=== "Skew comparison"

    ```bash
    poetry run voli ask-many --tickers SPY,QQQ,IWM "Show IV skew next Friday"
    ```

=== "Chain footprints"

    ```bash
    poetry run voli ask-many --tickers NVDA,TSLA,AAPL "Show options for 2026-05-16"
    ```

=== "JSON output"

    ```bash
    poetry run voli ask-many --json --tickers NVDA,SPY,QQQ \
      "ATM IV this week vs next week"
    ```

    ```json
    {
      "asof": null,
      "category": "term_structure",
      "prompt": "ATM IV this week vs next week",
      "rows": [
        {"ticker": "NVDA", "atm_strike": 100.0, "front_iv": 0.30,
         "next_iv": 0.35, "diff": 0.05, "status": "OK"},
        {"ticker": "SPY",  "atm_strike": 500.0, "front_iv": 0.30,
         "next_iv": 0.35, "diff": 0.05, "status": "OK"},
        {"ticker": "QQQ",  "atm_strike": 400.0, "front_iv": 0.30,
         "next_iv": 0.35, "diff": 0.05, "status": "OK"}
      ],
      "trace_id": null
    }
    ```

=== "With skeptic"

    ```bash
    poetry run voli ask-many --skeptic --tickers NVDA,SPY \
      "ATM IV this week vs next week"
    ```

    Aggregates skeptic concerns across rows (each line tagged with the
    ticker it came from).

## Failure handling

Per-ticker errors don't crash the batch — they show up as a `status=ERROR`
row with the exception message. Refused / unsupported per-ticker responses
get `status=REFUSED`.

```text
[ TERM STRUCTURE COMPARISON ]
TICKER   |  ATM_STRIKE  |  FRONT_IV  |  NEXT_IV  |    DIFF  |  STATUS
---------------------------------------------------------------------
NVDA     |         100  |    0.3000  |   0.3500  |  0.0500  |  OK
ZZZZZ    |           -  |        -   |       -   |       -  |  ERROR
SPY      |         500  |    0.3000  |   0.3500  |  0.0500  |  OK
```

Exit code is `0` when every row succeeded, `3` otherwise.

## Programmatic batch

```python
from voli.agent.batch import answer_many, comparison_rows

batch = answer_many(
    "ATM IV this week vs next week",
    ["NVDA", "SPY", "QQQ", "AAPL", "TSLA"],
)
for row in comparison_rows(batch):
    print(row)
```

## Performance

Batches run **sequentially** (one ticker at a time). The on-disk SQLite
cache means repeat tickers are essentially free; with a fresh cache
expect ~1-2 seconds per ticker against live Polygon (5-6 paginated HTTP
requests each).

A future opt-in threaded variant is possible — every per-ticker run is
isolated. Track the [project roadmap](https://github.com/playforest/voli/blob/main/todo.md).

## See also

- [Recipes](recipes.md) — watchlist patterns and shell pipelines.
- [Skeptic sub-agent](skeptic.md) — automatic quality review per row.
