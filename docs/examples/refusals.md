# Refusals & rewrites

Voli refuses prompts that need advice, prediction, execution, news
causality, or portfolio reasoning — and offers up to three **supported
rewrites** so you can keep moving.

## Anatomy of a refusal

```bash
poetry run voli ask "Should I buy NVDA calls?"
```

```text
================================================================================
 VOLI | TICKER: NVDA | CATEGORY: NOT_SUPPORTED | REFUSED
================================================================================
[ SUMMARY ]
Not supported in scope: this question falls under 'execution'. I can return
data, not recommendations.

[ REASON ]
execution

[ TRY INSTEAD ]
> Show ATM call and put for NVDA next week with bid/ask/mid.
================================================================================
```

Exit code: `3`.

## The reason taxonomy

| Reason | Triggered by | Why refused |
| --- | --- | --- |
| `advice` | "should I", "recommend", "advise", "best ..." | We provide data, not personalised guidance. |
| `execution` | "buy", "sell", "place order" | Out of scope; we don't connect to brokers. |
| `news` | "why did", "because of", "news", "earnings move" | We have no causal model of news. |
| `portfolio` | "portfolio", "my account", "P&L", "position size" | Out of scope; we don't reason about positions. |
| `strategy` | "best spread", "iron condor to trade", "credit spread" | Strategy recommendation = advice. |
| `prediction` | "predict", "will IV ...", "going to", "price target" | We don't forecast. |

The full keyword list lives in `voli.agent.planner._NOT_SUPPORTED_KEYWORDS`.

## Handling refusals in code

```python
from voli.agent import answer_question

resp = answer_question("Should I buy NVDA calls?")
if not resp.supported:
    print("REFUSED:", resp.facts["reason"])
    print("Try one of these instead:")
    for r in resp.suggested_rewrites:
        print("  ", r)
```

```text
REFUSED: execution
Try one of these instead:
   Show ATM call and put for NVDA next week with bid/ask/mid.
```

## Rewrites by reason

| Original prompt category | First suggested rewrite |
| --- | --- |
| `advice` | _"Show the option chain for [TICKER] front expiry around ATM, with bid/ask/mid."_ |
| `execution` | _"Show ATM call and put for [TICKER] next week with bid/ask/mid."_ |
| `news` | _"Compare ATM IV for [TICKER] front vs next expiry."_ |
| `portfolio` | _"Show greeks for [TICKER] ATM contract front expiry."_ |
| `strategy` | _"Show IV skew and ATM IV term structure for [TICKER]."_ |
| `prediction` | _"Show ATM IV term structure for [TICKER] over the next few expiries."_ |

`[TICKER]` is filled in from the prompt when present, otherwise reads
"your ticker".

## Missing-ticker fallback

A different kind of soft-refusal: the planner couldn't extract a ticker
and you didn't pass `--ticker`.

```bash
poetry run voli ask "Show ATM call and put this Friday"
```

```text
[ SUMMARY ]
I need a ticker to answer this. Please re-ask with the underlying (e.g.,
'NVDA ATM IV this week vs next week').
```

Exit code: `3`. Fix:

```bash
poetry run voli ask --ticker NVDA "Show ATM call and put this Friday"
```

## False positives

If a clearly in-scope prompt is being refused, the keyword rules in the
planner are too aggressive. Workaround: rephrase to drop the trigger word.
Long-term fix: tighten the heuristics — open an issue with the prompt and
expected category.

## See also

- [Concepts](../getting-started/concepts.md) — why we draw the line where we do.
- [`docs/v1_contract.md`](https://github.com/playforest/voli/blob/main/docs/v1_contract.md) — the formal contract.
