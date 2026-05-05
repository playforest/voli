# IV term structure

Compare ATM IV across expiries (front vs next, or longer chains).

## "ATM IV this week vs next week"

The canonical use case.

=== "CLI"

    ```bash
    poetry run oqe ask "NVDA ATM IV this week vs next week"
    ```

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

=== "Python"

    ```python
    from oqe.agent import answer_function as _  # placeholder
    from oqe.agent import answer_question

    resp = answer_question("NVDA ATM IV this week vs next week")
    print(f"diff = {resp.facts['next_iv'] - resp.facts['front_iv']:+.4f}")
    ```

=== "JSON"

    ```bash
    poetry run oqe ask --json "NVDA ATM IV this week vs next week" \
      | jq '{front: .facts.front_iv, next: .facts.next_iv,
             diff: (.facts.next_iv - .facts.front_iv)}'
    ```

    ```json
    {
      "front": 0.3318,
      "next":  0.3457,
      "diff":  0.0139
    }
    ```

## "Compare ATM IV for SPY front week vs next week"

Same shape, different ticker. The planner extracts SPY from the prompt.

```bash
poetry run oqe ask "Compare ATM IV for SPY front week vs next week"
```

## "Show IV term structure (ATM) for QQQ"

If you don't specify a comparison, the agent still emits the front-vs-next
table — that's the v1 default.

```bash
poetry run oqe ask "Show IV term structure (ATM) for QQQ"
```

## Programmatic batch

Compare front vs next IV across multiple tickers in one script:

```python
from oqe.agent import answer_question

tickers = ["NVDA", "SPY", "QQQ", "AAPL", "TSLA"]
print(f"{'TICKER':6}  {'FRONT IV':>9}  {'NEXT IV':>9}  {'DIFF':>9}")
for t in tickers:
    resp = answer_question(f"{t} ATM IV this week vs next week")
    if not resp.supported or resp.facts.get("front_iv") is None:
        print(f"{t:6}  (no data)")
        continue
    f = resp.facts["front_iv"]
    n = resp.facts["next_iv"]
    print(f"{t:6}  {f:>9.4f}  {n:>9.4f}  {n - f:>+9.4f}")
```

```text
TICKER  FRONT IV    NEXT IV       DIFF
NVDA      0.3318     0.3457    +0.0139
SPY       0.1543     0.1612    +0.0069
QQQ       0.1820     0.1935    +0.0115
AAPL      0.2210     0.2304    +0.0094
TSLA      0.4515     0.4620    +0.0105
```

## What gets logged in Facts

| Key | Type | Description |
| --- | --- | --- |
| `ticker` | str | Underlying. |
| `spot` | dict | `{value, ts, source}` for the underlying snapshot. |
| `right_used` | str | `"call"` (default) or `"put"` if the prompt requested puts. |
| `atm_strike` | float | Spot-nearest strike (tie-break: lower). |
| `front_expiry`, `next_expiry` | str | ISO dates. |
| `front_iv`, `next_iv` | float | ATM IVs at those expiries. |
| `flags` | list[str] | Analytics flags (`MISSING_IV`, `INSUFFICIENT_EXPIRIES`, ...). |

## Common follow-ups

- _"Which expiry has the highest ATM IV for NVDA in the next month?"_ → see
  [requirements.md](https://github.com/playforest/options-query-agent/blob/main/docs/requirements.md) for the v1 scope on multi-expiry term structure.
- Term structure on **puts** instead of calls: include "puts" in the prompt.

## See also

- [Skew](skew.md) for IV-vs-strike comparisons within one expiry.
- [Greeks](greeks.md) for ATM delta/gamma/theta/vega.
- [Analytics: term structure](../python-api/analytics.md#atm-iv-term-structure).
