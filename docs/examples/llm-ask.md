# LLM-driven agent (`oqe llm-ask`)

Where `oqe ask` uses a regex-based planner with a templated answer,
`oqe llm-ask` puts a real LLM in the driver's seat. The LLM receives the
prompt + a tool catalogue, decides which OQE tools to call, sees the
results, and writes the answer in its own words — grounded in the same
Polygon data the rule-based path uses.

## Pick a provider

OQE ships provider-agnostic. Install one (or both):

```bash
poetry install -E anthropic   # Claude (Sonnet 4.6 by default)
poetry install -E openai      # GPT (gpt-4.1-mini by default)
poetry install -E llm         # both
```

Set the matching API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
# or
export OPENAI_API_KEY=sk-...
```

If both keys are set and you don't pass `--provider`, OQE picks Anthropic.
Override with `--provider openai` or `OQE_LLM_PROVIDER=openai`.

## Run it

```bash
poetry run oqe llm-ask "How does NVDA's IV term structure compare to QQQ's?"
```

```text
================================================================================
 OQE LLM | PROVIDER: anthropic | MODEL: claude-sonnet-4-6
================================================================================
[ PROMPT ]
How does NVDA's IV term structure compare to QQQ's?

[ TOOL CALL ] list_option_contracts(ticker=NVDA, right=C, limit=200)
[ TOOL OK   ] {"meta": {...}, "contracts": [...]}

[ TOOL CALL ] get_option_greeks(option_symbols=[O:NVDA260509C00200000, ...])
[ TOOL OK   ] {"meta": {...}, "greeks": [{"option_symbol": ...}]}

[ TOOL CALL ] list_option_contracts(ticker=QQQ, right=C, limit=200)
[ TOOL OK   ] {"meta": {...}, "contracts": [...]}

[ TOOL CALL ] get_option_greeks(option_symbols=[O:QQQ260509C00400000, ...])
[ TOOL OK   ] {"meta": {...}, "greeks": [{"option_symbol": ...}]}

[ ANSWER ]
NVDA's near-term ATM IV is roughly twice QQQ's: 33.18% vs 18.20% for the
2026-05-09 expiry, and 34.57% vs 19.35% for 2026-05-16. Both names show a
similar absolute term-structure premium (~1.4 vol points front-to-next),
but as a percentage that's a smaller relative premium for NVDA (4.2%) than
for QQQ (6.3%) - mild signal that NVDA's near-term event risk is not
unusually elevated relative to its baseline level.
--------------------------------------------------------------------------------
stop_reason: end_turn  |  tool_calls: 4  |  tool_results: 4
================================================================================
```

You see each tool call as it happens (the live "chain of thought" log).

## Tool surface

Two layers, both exposed by default. The LLM is nudged (via the system
prompt) to prefer the analytics tools — they save round trips.

**Analytics tools (Stage B)** — one call each:

| Tool | Description |
| --- | --- |
| `compute_atm_iv_term_structure` | Front + next ATM IV, ATM strike, expiries, IV diff. Optional `max_relative_spread` filter. |
| `compute_skew_slope` | OLS slope of IV vs strike for one expiry (defaults to front). |
| `get_atm_greeks` | ATM contract's iv/delta/gamma/theta/vega for one expiry (defaults to front). |

**Raw Polygon tools (Stage A)** — for chain slices, custom strike windows,
or specific symbol lookups the analytics layer doesn't cover:

| Tool | Description |
| --- | --- |
| `get_underlying_snapshot` | Spot price + timestamp for a ticker. |
| `list_option_contracts` | Filterable contract list (expiry, right, strike range). |
| `get_option_quotes` | bid/ask/last/mid for a list of option symbols. |
| `get_option_greeks` | iv/delta/gamma/theta/vega for a list of option symbols. |

When using raw tools, call `list_option_contracts` first to get the
`option_symbol` identifiers, then fetch quotes/greeks by symbol.

To restrict the LLM to raw tools only (e.g. for testing chain reasoning):

```python
from oqe.llm import build_default_tools, llm_ask
from oqe.llm.provider import make_provider

tools = build_default_tools(include_analytics=False)   # raw only
result = llm_ask("...", provider=make_provider(), tools=tools)
```

## Flags

| Flag | Effect |
| --- | --- |
| `--provider {anthropic,openai}` | Override auto-detection. |
| `--model NAME` | Model name (overrides `$OQE_LLM_MODEL` and the default). |
| `--max-iterations N` | Cap on planner/tool/answer cycles (default 6). |
| `--json` | Append a JSON object with the final answer + tool log. |
| `--theme NAME` / `--no-color` / `--cycle-theme` | Same as `oqe ask`. |

## Programmatic

```python
from oqe.llm import build_default_tools, llm_ask
from oqe.llm.provider import make_provider
from oqe.llm.agent import collect

provider = make_provider("anthropic", model="claude-sonnet-4-6")
tools = build_default_tools()

result = collect(llm_ask("NVDA front vs next ATM IV", provider=provider, tools=tools))
print(result.answer)
print(f"{len(result.tool_calls)} tool calls, stop={result.stop_reason}")
```

`collect()` drains the event stream into an `AgentResult` for non-streaming
callers; loop the iterator yourself if you want live events.

## Adding a third provider

Implement `oqe.llm.provider.LLMProvider` (`start` / `step` /
`submit_tool_results`) yielding the neutral event types from
`oqe.llm.types`, then wire it into `make_provider`. The agent loop and CLI
don't need to change.

## When to use which

| Use case | Path |
| --- | --- |
| Deterministic, no API cost, fits an eval/regression test | `oqe ask` (rule-based) |
| Free-form / ambiguous question, qualitative comparison, multi-step reasoning | `oqe llm-ask` |
| Compare both sides of the architecture | Run both — same Polygon data underneath. |

## See also

- [Architecture: orchestrator](../architecture/orchestrator.md) — the rule-based agent.
- [Architecture: guardrails](../architecture/guardrails.md) — what the rule-based writer enforces (the LLM relies on its system prompt for the same intent).
- [Polygon tools](../python-api/tools.md) — the underlying data layer both paths share.
