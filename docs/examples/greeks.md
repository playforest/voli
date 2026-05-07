# Greeks

ATM greeks for the front expiry, plus a path to the Polygon-backed lower
level if you want greeks for any specific contract.

## "What are the greeks of the NVDA 2026-05-16 100C?"

The agent picks the ATM contract for that expiry/right and returns its
greeks.

```bash
poetry run voli ask "What are the greeks of the NVDA 2026-05-16 100C?"
```

```text
================================================================================
 VOLI | TICKER: NVDA | CATEGORY: GREEKS | OK
================================================================================
[ SUMMARY ]
NVDA ATM greeks: strike=200.0 iv=0.3318 delta=0.5012 gamma=0.0214 theta=-0.1041
vega=0.1183.

[ GREEKS ]
OPTION_SYMBOL          |  EXPIRY      |  STRIKE  |     IV  |   DELTA  |  GAMMA  |   THETA  |   VEGA
-----------------------------------------------------------------------------------------------------
O:NVDA260516C00200000  |  2026-05-16  |     200  |  0.3318 |  0.5012  |  0.0214 |  -0.1041 |  0.1183

[ FACTS ]
TICKER        NVDA
SPOT          value=199.8450  ts=2026-05-05T13:09:04Z  source=polygon
RIGHT_USED    call
ATM_CONTRACT  option_symbol=O:NVDA260516C00200000  expiry=2026-05-16  strike=200  iv=0.3318  ...
================================================================================
```

## "Show delta/gamma/theta/vega for the 5 strikes around ATM for SPY this Friday"

The v1 writer renders **one** ATM contract per request. Multi-strike greeks
tables are a v1.x roadmap item; for now the request is supported but only
the ATM row appears.

## Programmatic ATM greeks

```python
from voli.agent import answer_question

resp = answer_question("What are the greeks of the NVDA 2026-05-16 100C?")
ag = resp.facts["atm_contract"]
print(f"strike={ag['strike']}, iv={ag['iv']:.4f}")
print(f"delta={ag['delta']:+.4f}, gamma={ag['gamma']:.4f}")
print(f"theta={ag['theta']:+.4f}, vega={ag['vega']:.4f}")
```

```text
strike=200.0, iv=0.3318
delta=+0.5012, gamma=0.0214
theta=-0.1041, vega=0.1183
```

## Greeks for a specific contract (lower level)

If you know the option symbol, hit the tool layer directly:

```python
from voli.tools.polygon_tools import get_option_greeks
from voli.tool_schemas import GetOptionGreeksInput

resp = get_option_greeks(GetOptionGreeksInput(option_symbols=[
    "O:NVDA260516C00200000",
    "O:NVDA260516C00205000",
    "O:NVDA260516C00210000",
]))
for g in resp.greeks:
    print(f"{g.option_symbol}  iv={g.iv:.4f}  delta={g.delta:+.4f}")
```

```text
O:NVDA260516C00200000  iv=0.3318  delta=+0.5012
O:NVDA260516C00205000  iv=0.3402  delta=+0.4287
O:NVDA260516C00210000  iv=0.3508  delta=+0.3601
```

## Vendor noise: tiny negative gamma/vega

Polygon occasionally emits gamma `~ -3e-10` or vega `~ -8e-5` — artefacts
of upstream Black-Scholes solvers. We clamp anything within `1e-3` of zero
to exactly `0.0` in `voli.polygon.normalise._clamp_nonneg`. Genuinely
negative values still raise (those would indicate a real upstream bug).

If you're calling the tool layer directly, expect `gamma=0.0` for
deep-OTM contracts even when the raw API returned a tiny negative.

## Facts shape

| Key | Type |
| --- | --- |
| `ticker` | str |
| `spot` | dict |
| `right_used` | str |
| `atm_contract` | dict with `option_symbol`, `expiry`, `strike`, `iv`, `delta`, `gamma`, `theta`, `vega` |
| `flags` | list[str] |

## See also

- [Polygon tools](../python-api/tools.md) — direct API access.
- [Analytics: ATM greeks](../python-api/analytics.md#atm-greeks).
