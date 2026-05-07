# `answer_question`

The single public entrypoint for the agent. Wraps the planner → executor →
writer pipeline behind one function call.

## Signature

```python
from voli.agent import answer_question, ToolRegistry, AnswerResponse

def answer_question(
    prompt: str,
    *,
    ticker_default: str | None = None,
    registry: ToolRegistry | None = None,
) -> AnswerResponse:
    ...
```

| Parameter | Purpose |
| --- | --- |
| `prompt` | Natural-language question (any string). |
| `ticker_default` | Fallback ticker when the prompt doesn't include one. |
| `registry` | Override the tool registry. Default: `default_registry()` (Polygon-backed). Tests pass a stub registry. |

## Returns

An `AnswerResponse` — a frozen dataclass:

```python
@dataclass(frozen=True)
class AnswerResponse:
    supported: bool                 # False for refusals + missing-ticker
    category: str                   # 'chain' | 'term_structure' | 'skew' | 'greeks' | 'not_supported'
    summary: str                    # short narrative
    table: dict[str, Any]           # {"type": "...", "rows": [...]}
    facts: dict[str, Any]           # raw audit-trail fields
    numbers_used: list[float]       # every number summary may reference
    limitations: list[str]          # non-fatal warnings (STALE_DATA, ...)
    suggested_rewrites: list[str]   # only for refusals
```

## Examples

### Basic

```python
from voli.agent import answer_question

resp = answer_question("NVDA ATM IV this week vs next week")
assert resp.supported
print(resp.summary)
print("front IV:", resp.facts["front_iv"])
print("next  IV:", resp.facts["next_iv"])
```

```text
NVDA ATM IV term structure: front IV 0.3318 vs next IV 0.3457 at strike 200.0 (diff 0.0139).
front IV: 0.3318
next  IV: 0.3457
```

### With a ticker default

```python
resp = answer_question(
    "Show ATM call and put this Friday",
    ticker_default="NVDA",
)
```

### Refusal handling

```python
resp = answer_question("Should I buy NVDA calls?")
if not resp.supported:
    print("REFUSED:", resp.facts["reason"])
    for r in resp.suggested_rewrites:
        print("  try:", r)
```

```text
REFUSED: execution
  try: Show ATM call and put for NVDA next week with bid/ask/mid.
```

### Programmatic batch (offline)

```python
from voli.agent import answer_question
from voli.eval.synth_market import make_registry

reg = make_registry()
prompts = [
    "NVDA ATM IV this week vs next week",
    "Show NVDA IV skew next Friday",
    "What are the greeks of the NVDA 2026-05-16 100C?",
]
for p in prompts:
    resp = answer_question(p, registry=reg)
    print(f"{resp.category:18}  {resp.summary[:60]}")
```

```text
term_structure      NVDA ATM IV term structure: front IV 0.3 vs next IV 0.35
skew                NVDA skew slope: OLS slope 0.0 (IV vs strike) at front e
greeks              NVDA ATM greeks: strike=100.0 iv=0.3 delta=0.5 gamma=0.0
```

## Error handling

- **Network / API errors**: tool calls raise an exception that propagates
  out of `answer_question`. The CLI catches these and renders the error
  block; library callers can `try/except` themselves.
- **Refusals are not exceptions**: they return `AnswerResponse(supported=False, ...)`.
- **Guardrail violations**: extremely rare (writer wouldn't ship them
  silently) — the writer raises `voli.agent.writer.GuardrailViolation`.

## Performance

- First call against a ticker: 4-6 Polygon HTTP requests for the chain.
- Subsequent calls within the cache TTL (30s for snapshots, 6h for
  contract lists): zero HTTP, served from `~/.voli/cache.sqlite`.
- Synthetic registry: pure Python, ~milliseconds.

## See also

- [Agent internals](agent.md) — planner / executor / writer dataclasses
- [Analytics](analytics.md) — the metric functions answer_question uses
- [Polygon tools](tools.md) — the underlying tool layer
