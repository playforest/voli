# LLM-driven agent (`voli llm-ask`)

Where `voli ask` uses a regex-based planner with a templated answer,
`voli llm-ask` puts a real LLM in the driver's seat. The LLM receives the
prompt + a tool catalogue, decides which Voli tools to call, sees the
results, and writes the answer in its own words — grounded in the same
Polygon data the rule-based path uses.

## Pick a provider

Voli ships provider-agnostic. Install one (or both):

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

If both keys are set and you don't pass `--provider`, Voli picks Anthropic.
Override with `--provider openai` or `VOLI_LLM_PROVIDER=openai`.

## Run it

```bash
poetry run voli llm-ask "How does NVDA's IV term structure compare to QQQ's?"
```

```text
================================================================================
 VOLI LLM | PROVIDER: anthropic | MODEL: claude-sonnet-4-6
================================================================================
[ PROMPT ]
How does NVDA's IV term structure compare to QQQ's?

[ TOOL CALL ] compute_atm_iv_term_structure(ticker=NVDA)
[ TOOL OK   (polygon) ] {"ticker": "NVDA", "front_iv": 0.3318, ..., "primary_source": "polygon"}

[ TOOL CALL ] compute_atm_iv_term_structure(ticker=QQQ)
[ TOOL OK   (cache) ] {"ticker": "QQQ", "front_iv": 0.1820, ..., "primary_source": "cache"}

[ ANSWER ]
NVDA's near-term ATM IV is roughly twice QQQ's: 33.18% vs 18.20% for the
2026-05-09 expiry, and 34.57% vs 19.35% for 2026-05-16. Both names show a
similar absolute term-structure premium (~1.4 vol points front-to-next),
but as a percentage that's a smaller relative premium for NVDA (4.2%) than
for QQQ (6.3%) - mild signal that NVDA's near-term event risk is not
unusually elevated relative to its baseline level.
--------------------------------------------------------------------------------
stop_reason: end_turn  |  tool_calls: 2  |  tool_results: 2
================================================================================
```

You see each tool call as it happens (the live "chain of thought" log).

### Cache vs polygon marker

Each `[ TOOL OK ]` line is tagged with where the data came from:

| Marker | Meaning |
| --- | --- |
| `[ TOOL OK   (cache) ]` | Served entirely from the on-disk SQLite TTL cache (`~/.voli/cache.sqlite`) — no Polygon HTTP call. |
| `[ TOOL OK   (polygon) ]` | Fresh fetch from Polygon. |
| `[ TOOL OK   (mixed) ]` | Analytics-tool only: the underlying-snapshot lookup and the chain pull came from different sources (one cache, one network). |
| `[ TOOL OK   ]` | The tool result didn't carry a source field (custom tool, MCP-only, etc.). |

The same label is also embedded in the JSON the LLM receives (analytics
tools: `primary_source`; raw tools: `meta.primary_source`), so the model
can refer to it when assessing freshness. To see Polygon HTTP traffic
mid-run, set `POLYGON_HTTP_DEBUG=1` and watch stderr — every line that
isn't there means cache.

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
from voli.llm import build_default_tools, llm_ask
from voli.llm.provider import make_provider

tools = build_default_tools(include_analytics=False)   # raw only
result = llm_ask("...", provider=make_provider(), tools=tools)
```

## Flags

| Flag | Effect |
| --- | --- |
| `--provider {anthropic,openai}` | Override auto-detection. |
| `--model NAME` | Model name (overrides `$VOLI_LLM_MODEL` and the default). |
| `--max-iterations N` | Cap on planner/tool/answer cycles (default 6). |
| `--json` | Append a JSON object with the final answer + tool log. |
| `--skeptic` | Run the skeptic on the LLM's tool results. Appends a `[ SKEPTIC ]` block. |
| `--trace` | Open a JSONL run-trace **and** write a `<id>.llm.json` companion so `voli replay` can re-render later. |
| `--theme NAME` / `--no-color` / `--cycle-theme` | Same as `voli ask`. |

## Skeptic on LLM answers

Same `[ SKEPTIC ]` block as `voli ask --skeptic`. The reviewer walks the
LLM's tool results and surfaces:

| Code | Trigger |
| --- | --- |
| `STALE_SNAPSHOT` | Spot snapshot's `ts` older than 30 minutes. |
| `ATM_GAP` | Analytics-tool result has `atm_strike` >5% from spot. |
| `TOOL_ERROR` | A tool returned an `{"error": ...}` payload (critical). |
| `STALE_DATA` / `PARTIAL_DATA` / `NO_RESULTS` / ... | Forwarded from `meta.warnings` on the polygon tool wrappers. |
| Analytics flags (e.g. `FILTERED_WIDE_SPREAD`) | Forwarded from analytics tool `flags` arrays. |

```bash
poetry run voli llm-ask --skeptic "What's NVDA's ATM IV term structure?"
```

```text
... [ ANSWER ] ...

[ SKEPTIC ]
WARN      STALE_SNAPSHOT            spot snapshot is 47m old (threshold 30m).
INFO      VENDOR_LIMIT              tool layer flagged VENDOR_LIMIT.
```

## Replay an LLM answer

```bash
# Capture
poetry run voli llm-ask --trace "What's NVDA's IV term structure?"
# ... output ...
# replay companion: ~/.voli/traces/<id>.llm.json

# Replay later (no API call, no Polygon traffic)
poetry run voli replay <trace_id>
```

`voli replay` auto-detects the companion shape (`<id>.response.json` for
the rule-based path, `<id>.llm.json` for LLM mode) and re-renders through
the same themed blocks. Pivot themes or output format on the replay:

```bash
poetry run voli replay --theme matrix <trace_id>
poetry run voli replay --json         <trace_id>
```

If `--skeptic` was set on the original run, the concerns are preserved in
the companion and re-rendered on replay.

## Programmatic

```python
from voli.llm import build_default_tools, llm_ask
from voli.llm.provider import make_provider
from voli.llm.agent import collect

provider = make_provider("anthropic", model="claude-sonnet-4-6")
tools = build_default_tools()

result = collect(llm_ask("NVDA front vs next ATM IV", provider=provider, tools=tools))
print(result.answer)
print(f"{len(result.tool_calls)} tool calls, stop={result.stop_reason}")
```

`collect()` drains the event stream into an `AgentResult` for non-streaming
callers; loop the iterator yourself if you want live events.

## Adding a third provider

Implement `voli.llm.provider.LLMProvider` (`start` / `step` /
`submit_tool_results`) yielding the neutral event types from
`voli.llm.types`, then wire it into `make_provider`. The agent loop and CLI
don't need to change.

## When to use which

| Use case | Path |
| --- | --- |
| Deterministic, no API cost, fits an eval/regression test | `voli ask` (rule-based) |
| Free-form / ambiguous question, qualitative comparison, multi-step reasoning | `voli llm-ask` |
| Compare both sides of the architecture | Run both — same Polygon data underneath. |

## See also

- [Architecture: orchestrator](../architecture/orchestrator.md) — the rule-based agent.
- [Architecture: guardrails](../architecture/guardrails.md) — what the rule-based writer enforces (the LLM relies on its system prompt for the same intent).
- [Polygon tools](../python-api/tools.md) — the underlying data layer both paths share.
