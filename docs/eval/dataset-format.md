# Dataset format

`eval/prompts.jsonl` is a JSON-lines file: one JSON object per line. Lines
beginning with `//` are skipped (comment-friendly).

## Per-case schema

```json
{
  "id":                       "tc_001",
  "prompt":                   "NVDA ATM IV this week vs next week.",
  "ticker_default":           null,
  "expected_supported":       true,
  "expected_category":        "term_structure",
  "expected_ticker":          "NVDA",
  "expected_tools":           ["get_underlying_snapshot",
                               "list_option_contracts",
                               "get_option_greeks"],
  "expected_compute":         "term_structure",
  "expected_table_type":      "term_structure",
  "must_contain_in_summary":  ["NVDA", "ATM IV", "term structure"],
  "must_have_facts_keys":     ["ticker", "spot", "atm_strike",
                               "front_iv", "next_iv"],
  "expected_metrics":         {"atm_strike": 100.0, "front_iv": 0.30,
                               "next_iv": 0.35},
  "metrics_tolerance":        1e-6
}
```

Every field except `id` and `prompt` is optional — the corresponding check
is skipped when absent.

## Field reference

| Field | Type | Effect |
| --- | --- | --- |
| `id` | string | Unique case identifier; used in pytest IDs and failure messages. |
| `prompt` | string | The natural-language prompt fed to `answer_question`. |
| `ticker_default` | string \| null | Passed as `ticker_default=` to the agent. |
| `expected_supported` | bool | Asserts `resp.supported`. |
| `expected_category` | string | Asserts `resp.category`. |
| `expected_ticker` | string | Asserts `resp.facts["ticker"]`. |
| `expected_tools` | string[] | Asserts the **exact** ordered tool sequence the executor invoked. |
| `expected_compute` | string \| null | (Currently unused; reserved for future analytics-step assertions.) |
| `expected_table_type` | string | Asserts `resp.table["type"]`. |
| `must_contain_in_summary` | string[] | Each substring must appear in `resp.summary`. |
| `must_have_facts_keys` | string[] | Each key must exist in `resp.facts`. |
| `expected_metrics` | dict[str, float] | Each scalar Facts field must equal the expected value within tolerance. |
| `metrics_tolerance` | float | Absolute tolerance for `expected_metrics`. Default `1e-6`. |

## Synthetic surface (what to encode)

The harness uses the registry from `voli.eval.synth_market`. The IV
formula is:

```
base = 0.30
if expiry_index == 1: base += 0.05      # next-week premium
if right == "P":      base += 0.03      # put skew
base += 0.002 * abs(strike - spot)      # symmetric V-shape smile
```

Spots:

| Ticker | Spot |
| --- | --- |
| NVDA | 100.0 |
| SPY  | 500.0 |
| QQQ  | 400.0 |
| AAPL | 200.0 |
| TSLA | 250.0 |
| IWM  | 220.0 |
| MSFT | 410.0 |

Two expiries per ticker (`2026-05-09`, `2026-05-16`), 11 strikes per
expiry per right (spot ± 5 × $5).

So: `NVDA front C ATM = 0.30`, `NVDA next C ATM = 0.35`, `NVDA front P
ATM = 0.33`, etc.

For chain-count assertions:

| Filter | contracts_count |
| --- | --- |
| Both expiries, both rights, no strike filter | 44 |
| One expiry, both rights | 22 |
| One expiry, one right | 11 |
| Both expiries, one right | 22 |

## Tolerance guidance

| Metric | Recommended `metrics_tolerance` |
| --- | --- |
| Strike values (round numbers) | `1e-9` |
| IV values | `1e-6` |
| Skew slope (numerically computed) | `1e-9` |
| Counts (integers) | omit or `0` |

## Comments

Lines starting with `//` are stripped by `voli.eval.runner.load_cases`.
Use them to group cases or note regressions:

```jsonl
// term_structure (Part 5 metrics)
{"id": "tc_001", ...}
{"id": "tc_002", ...}

// regressions for v1.2 issue #42
{"id": "tc_re01", ...}
```

## See also

- [Running the harness](harness.md) — invocation + output.
- [Adding cases](adding-cases.md) — workflow for new entries.
