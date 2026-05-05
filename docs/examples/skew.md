# Skew

How IV varies across strikes for a single expiry. v1 ships an OLS slope
metric; risk reversal (25Δ put IV − 25Δ call IV) is on the roadmap.

## "Show NVDA IV skew for next Friday"

```bash
poetry run oqe ask "Show NVDA IV skew for next Friday"
```

```text
================================================================================
 OQE | TICKER: NVDA | CATEGORY: SKEW | OK
================================================================================
[ SUMMARY ]
NVDA skew slope: OLS slope -0.0021 (IV vs strike) at front expiry 2026-05-16.

[ SKEW ]
FRONT_EXPIRY  |  ATM_STRIKE  |    SLOPE
----------------------------------------
2026-05-16    |         200  |  -0.0021

[ FACTS ]
TICKER        NVDA
SPOT          value=199.8450  ts=2026-05-05T13:09:04Z  source=polygon
RIGHT_USED    call
FRONT_EXPIRY  2026-05-16
ATM_STRIKE    200
SKEW_SLOPE    -0.0021
FLAGS         (none)
================================================================================
```

## What the slope means

`skew_slope` is the OLS slope of `IV ~ strike` across the front expiry's
strike grid (calls only by default).

| Slope | Interpretation |
| --- | --- |
| `~ 0` | Flat smile / no directional skew. |
| `< 0` | Higher IV at lower strikes (downside protection bid). Typical for index ETFs. |
| `> 0` | Higher IV at higher strikes (upside skew). Common in single-name names with takeover speculation. |

## "What's the skew slope across strikes for TSLA next week?"

```bash
poetry run oqe ask "What's the skew slope across strikes for TSLA next week?"
```

## Programmatic batch

```python
from oqe.agent import answer_question

for ticker in ["SPY", "QQQ", "NVDA", "TSLA"]:
    resp = answer_question(f"Show {ticker} IV skew next Friday")
    slope = resp.facts.get("skew_slope")
    if slope is None:
        print(f"{ticker:5}  (no data)")
        continue
    print(f"{ticker:5}  slope={slope:+.4f}")
```

```text
SPY    slope=-0.0028
QQQ    slope=-0.0019
NVDA   slope=-0.0021
TSLA   slope=-0.0034
```

## Spread filtering (Python only)

The CLI uses defaults; if you call the analytics directly you can drop
illiquid strikes via `max_relative_spread`:

```python
from oqe.analytics.skew import skew_slope
from oqe.analytics.metrics_bundle import compute_v1_metrics_bundle

bundle = compute_v1_metrics_bundle(
    spot=199.84,
    contracts=my_contracts,
    greeks_by_symbol=my_greeks,
    quotes_by_symbol=my_quotes,
    max_relative_spread=0.20,    # drop strikes with > 20% bid-ask spread
    right="call",
)
print(bundle.skew_slope.value, bundle.skew_slope.flags)
```

`flags` will include `FILTERED_WIDE_SPREAD` for each excluded strike, so
you can audit the filter's effect.

## Facts shape

| Key | Type |
| --- | --- |
| `ticker` | str |
| `spot` | dict |
| `right_used` | str (`"call"` by default) |
| `front_expiry` | str (ISO date) |
| `atm_strike` | float |
| `skew_slope` | float |
| `flags` | list[str] |

## Limitations

- v1 implements **OLS slope only**. Risk reversal and 25Δ-bucket metrics
  require a delta-bucket selection pass that's planned for v1.x.
- Skew is computed on **calls only by default**. To run on puts, include
  "puts" in the prompt, or call the analytics function with `right="put"`.

## See also

- [Term structure](term-structure.md) for IV across expiries.
- [Analytics: skew slope](../python-api/analytics.md#skew-slope).
