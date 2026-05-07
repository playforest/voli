# Your first query

The CLI's main job is `voli ask "..."`. This walkthrough sends a real
question, explains every part of the output, and shows the JSON equivalent
for scripting.

## Run it

```bash
poetry run voli ask "NVDA ATM IV this week vs next week"
```

```text
================================================================================
 VOLI | TICKER: NVDA | CATEGORY: TERM_STRUCTURE | OK
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
FLAGS         (none)

[ LIMITATIONS ]
! STALE_DATA
================================================================================
```

## Anatomy of the output

| Section | What it tells you |
| --- | --- |
| **Status bar** | Ticker, category, OK/REFUSED marker, optional theme name. |
| **`[ SUMMARY ]`** | One short narrative sentence. Every number here is enforced to come from `numbers_used` (the writer raises if it sees a number not present in the analytics output). |
| **`[ TERM STRUCTURE ]`** | The category-specific table. Other categories produce `[ CHAIN SLICE ]`, `[ SKEW ]`, or `[ GREEKS ]`. |
| **`[ FACTS ]`** | Raw fields the summary references, plus timestamps and data source. This is the audit trail. |
| **`[ LIMITATIONS ]`** | Non-fatal warnings (stale snapshot, partial data, vendor caveats). |

!!! note "Why no emojis?"

    The renderer is intentionally serious — Bloomberg Terminal aesthetic. If
    you want a different vibe, [pick another theme](../cli/themes.md).

## Same query, different shapes

=== "Themed text (default)"

    ```bash
    poetry run voli ask "NVDA ATM IV this week vs next week"
    ```

=== "JSON for scripting"

    ```bash
    poetry run voli ask --json "NVDA ATM IV this week vs next week"
    ```

    ```json
    {
      "asof": null,
      "category": "term_structure",
      "facts": {
        "atm_strike": 200.0,
        "front_expiry": "2026-05-09",
        "front_iv": 0.3318,
        "next_expiry": "2026-05-16",
        "next_iv": 0.3457,
        "right_used": "call",
        "spot": {"source": "polygon", "ts": "2026-05-05T13:09:04Z", "value": 199.84},
        "ticker": "NVDA"
      },
      "summary": "NVDA ATM IV term structure: front IV 0.3318 vs next IV 0.3457 at strike 200.0 (diff 0.0139).",
      "supported": true,
      "table": {"type": "term_structure", "rows": [...]},
      "numbers_used": [199.84, 200.0, 0.3318, 0.3457, 0.0139],
      "limitations": ["STALE_DATA"],
      "trace_id": null
    }
    ```

=== "Different theme"

    ```bash
    poetry run voli ask --theme matrix "NVDA ATM IV this week vs next week"
    ```

=== "Pipe-friendly"

    ```bash
    poetry run voli ask "NVDA ATM IV this week vs next week" | head -20
    ```

    Colour auto-disables when stdout isn't a TTY.

## Same query in Python

```python
from voli.agent import answer_question

resp = answer_question("NVDA ATM IV this week vs next week")
print(f"Front IV: {resp.facts['front_iv']:.4f}")
print(f"Next IV : {resp.facts['next_iv']:.4f}")
print(f"Diff    : {resp.facts['next_iv'] - resp.facts['front_iv']:+.4f}")
```

```text
Front IV: 0.3318
Next IV : 0.3457
Diff    : +0.0139
```

## Exit codes

| Code | Meaning | When |
| --- | --- | --- |
| `0` | Success | Supported question, answer rendered. |
| `2` | Argparse error | Unknown flag, bad value, etc. |
| `3` | Refused | Out of scope (advice, prediction, ...) or missing ticker. |
| `4` | Upstream error | Polygon failure, missing API key, etc. Rendered in the themed error block. |

Useful in shell scripts:

```bash
if poetry run voli ask --json "NVDA ATM IV this week" > /tmp/answer.json; then
  jq '.facts.front_iv' /tmp/answer.json
else
  echo "ask failed: $?"
fi
```

## Next

- [Concepts](concepts.md) — what the agent does and refuses
- [CLI overview](../cli/overview.md) — every flag in detail
- [Examples cookbook](../examples/term-structure.md) — one page per category
