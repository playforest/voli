# Analytics

Pure-function metric calculators in `voli.analytics`. The agent calls these
internally; you can also call them directly if you have your own chain
snapshots.

## Modules

```python
from voli.analytics.iv_metrics import (
    atm_iv_term_structure,
    select_atm_strike,
    mid_price,
    relative_spread,
)
from voli.analytics.skew import skew_slope, strike_iv_pairs, delta_skew
from voli.analytics.greeks import atm_greeks_for_expiry
from voli.analytics.metrics_bundle import compute_v1_metrics_bundle
```

## ATM IV term structure

```python
from voli.analytics.iv_metrics import atm_iv_term_structure

result = atm_iv_term_structure(
    spot=100.0,
    contracts=my_contracts,             # list of OptionContract
    greeks_by_symbol=my_greeks_map,     # {symbol: OptionGreeks}
    right="call",
)
print(result.atm_strike, result.front_iv, result.next_iv)
print(result.flags)                     # ('MISSING_IV', ...) if data was incomplete
```

Returns a `TermStructureResult` with `.atm_strike`, `.front_expiry`,
`.next_expiry`, `.front_iv`, `.next_iv`, `.flags`.

## Skew slope

```python
from voli.analytics.skew import skew_slope
from datetime import date

slope = skew_slope(
    contracts=my_contracts,
    greeks_by_symbol=my_greeks_map,
    expiry=date(2026, 5, 16),
    right="call",
)
print(slope.value, slope.flags)
```

OLS slope of IV vs strike. Returns a `MetricResult[float]` whose `.value`
is `None` when there are fewer than 2 points or zero variance.

### Spread filtering

Optional: pass quotes and a max relative spread to drop illiquid points
deterministically.

```python
slope = skew_slope(
    contracts=my_contracts,
    greeks_by_symbol=my_greeks_map,
    quotes_by_symbol=my_quotes_map,
    max_relative_spread=0.20,           # exclude > 20% bid-ask spread
    expiry=date(2026, 5, 16),
    right="call",
)
```

## ATM greeks

```python
from voli.analytics.greeks import atm_greeks_for_expiry

snap = atm_greeks_for_expiry(
    spot=100.0,
    contracts=my_contracts,
    greeks_by_symbol=my_greeks_map,
    expiry=date(2026, 5, 16),
    right="call",
)
print(snap.value.delta, snap.value.gamma, snap.value.iv)
```

Returns a `MetricResult[GreeksSnapshot]` — `snap.value` is `None` if no
matching contract or no greeks available.

## One-shot bundle

```python
from voli.analytics.metrics_bundle import compute_v1_metrics_bundle

bundle = compute_v1_metrics_bundle(
    spot=100.0,
    contracts=my_contracts,
    greeks_by_symbol=my_greeks_map,
    right="call",
    quotes_by_symbol=my_quotes_map,    # optional
    max_relative_spread=0.20,          # optional
)

print(bundle.term_structure.atm_strike)
print(bundle.skew_slope.value)
print(bundle.atm_greeks.value.delta)
```

This is what the agent calls. Convenient when you have all three metrics
in mind and want one round trip through the data.

## ATM strike selection

```python
from voli.analytics.iv_metrics import select_atm_strike

strike = select_atm_strike(
    spot=102.5,
    strikes=[95, 100, 105, 110],
    tie_break="lower",                  # or "higher"
)
print(strike.value)                     # 100.0
```

Deterministic: ties (e.g. spot 102.5 vs strikes 100 and 105 both 2.5 away)
break by configurable rule. Default `"lower"`.

## Mid price

```python
from voli.analytics.iv_metrics import mid_price

mid = mid_price(bid=10.0, ask=10.5, last=10.2)
print(mid.value, mid.flags)             # 10.25, ()
```

Order: `(bid + ask) / 2` if both present and `ask >= bid`; else `last`;
else `bid`; else `ask`; else `None`. Diagnostic flags propagate (e.g.
`MID_FROM_LAST`, `INVALID_BID_ASK`).

## Why `MetricResult[T]`?

A frozen dataclass `(value, flags)` so functions never raise on missing
data — they return `None` with diagnostic flags the writer can disclose
to the user. Keeps the agent's "no invented numbers" rule auditable.

## See also

- [`docs/metrics_definitions.md`](https://github.com/playforest/voli/blob/main/docs/metrics_definitions.md) for the formal definitions.
- [`voli.analytics.protocols`](https://github.com/playforest/voli/blob/main/src/voli/analytics/protocols.py) for the duck-typed interfaces these functions accept.
