# Chain slices

Raw bid/ask/mid/last for a slice of the option chain. The agent returns
the contracts and their quotes; analytics aren't applied (unlike the
term-structure / skew / greeks paths).

## "Show NVDA options expiring this Friday"

```bash
poetry run oqe ask "Show NVDA options expiring this Friday"
```

```text
================================================================================
 OQE | TICKER: NVDA | CATEGORY: CHAIN | OK
================================================================================
[ SUMMARY ]
NVDA chain slice: 22 contracts returned. Spot 199.8450.

[ CHAIN SLICE ]
OPTION_SYMBOL          |  EXPIRY      |  RIGHT  |  STRIKE  |  BID    |  ASK   |  MID    |  LAST   |  TS
-------------------------------------------------------------------------------------------------------
O:NVDA260509C00190000  |  2026-05-09  |  C      |     190  |  10.20  |  10.45 |  10.325 |  10.30  |  ...
O:NVDA260509C00195000  |  2026-05-09  |  C      |     195  |   6.50  |   6.70 |   6.60  |   6.55  |  ...
... (20 more rows) ...

[ FACTS ]
TICKER         NVDA
SPOT           value=199.8450  ts=...  source=polygon
CONTRACTS_COUNT 22
EXPIRIES_USED  2026-05-09
RIGHT_FILTER   BOTH
================================================================================
```

## "List NVDA calls for 2026-05-09 between 90 and 110"

The planner extracts the ISO date and `calls`. Strike-window words
("between 90 and 110") aren't parsed in v1 — the contracts list comes back
broader, and you can filter client-side.

```bash
poetry run oqe ask "List NVDA calls for 2026-05-09 between 90 and 110"
```

## Programmatic chain access

```python
from oqe.agent import answer_question

resp = answer_question("Show NVDA options expiring this Friday")
for row in resp.table["rows"][:5]:
    bid = row["bid"]
    ask = row["ask"]
    mid = row["mid"]
    print(f"{row['option_symbol']:25}  bid={bid:>6}  ask={ask:>6}  mid={mid:>6}")
```

```text
O:NVDA260509C00190000  bid= 10.20  ask= 10.45  mid=10.325
O:NVDA260509C00195000  bid=  6.50  ask=  6.70  mid=  6.60
O:NVDA260509C00200000  bid=  3.10  ask=  3.30  mid=  3.20
O:NVDA260509P00190000  bid=  0.80  ask=  0.95  mid= 0.875
O:NVDA260509P00195000  bid=  1.55  ask=  1.75  mid=  1.65
```

## "Show TSLA chain"

The most generic chain query — both rights, all listed expiries (subject to
the 250-per-page Polygon limit per request).

```bash
poetry run oqe ask "Show TSLA chain"
```

## Filtering for liquid contracts

If you want to drop wide spreads, work at the analytics or quote layer:

```python
from oqe.analytics.iv_metrics import is_quote_spread_too_wide
from oqe.agent import answer_question

resp = answer_question("Show NVDA options expiring this Friday")
liquid = []
for row in resp.table["rows"]:
    bid, ask = row.get("bid"), row.get("ask")
    if bid is None or ask is None:
        continue
    if (ask - bid) / ((bid + ask) / 2) > 0.20:
        continue
    liquid.append(row)
print(f"{len(liquid)} of {len(resp.table['rows'])} contracts within 20% spread")
```

## Facts shape

| Key | Type |
| --- | --- |
| `ticker` | str |
| `spot` | dict |
| `contracts_count` | int |
| `expiries_used` | list[str] |
| `right_filter` | str (`"BOTH"`, `"C"`, or `"P"`) |

## See also

- [Polygon tools](../python-api/tools.md) — direct contract listing.
- [Term structure](term-structure.md) — analytics over the chain.
