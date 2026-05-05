# Agent flow (Part 6)

The agent is a small, deterministic state machine. Every prompt walks through
the same four stages so behaviour is predictable and testable.

```
prompt
  -> planner   ── parses Intent, builds a Plan (tool steps + compute step)
  -> executor  ── runs each PlanStep against a ToolRegistry; computes metrics
  -> writer    ── renders summary + table + Facts and enforces guardrails
  -> AnswerResponse
```

## Why a heuristic planner (no LLM in v1)?

- Tests are deterministic with no network or model dependencies.
- The contract from `docs/v1_contract.md` ("never invent numbers") is easier to
  enforce when the orchestrator is a pure function of its inputs.
- Swapping in an LLM-backed planner later only requires producing the same
  `Intent` / `Plan` shape; the rest of the pipeline doesn't change.

## Modules

| Module | Responsibility |
| --- | --- |
| `oqe.agent.state` | `Intent`, `PlanStep`, `Plan`, `AgentState`, `AnswerResponse` dataclasses. |
| `oqe.agent.planner` | Prompt -> `Intent` -> `Plan`. Uses regex/keyword rules. Categorizes prompts as one of: chain, term_structure, skew, greeks, not_supported. |
| `oqe.agent.executor` | Runs plan steps via a `ToolRegistry`. Resolves late-bound inputs (e.g. quotes need the contract list). Calls analytics from `oqe.analytics.metrics_bundle`. |
| `oqe.agent.writer` | Per-category renderer. Produces summary, table, facts. Enforces guardrails. |

## Tool registry

`ToolRegistry` maps tool name -> callable. The default registry wires up the
real Polygon-backed tools from `oqe.tools.polygon_tools`; tests inject stub
callables that return synthetic objects matching the same attribute shape.
This keeps the agent layer decoupled from network I/O.

## Plan shape

`Plan.steps` is an ordered tuple of `PlanStep`s. Each step has a tool name,
an inputs dict, and a label. Steps that depend on prior outputs use the
sentinel `"option_symbols_from": "<label>"`; the executor resolves it before
calling the tool. The optional `Plan.compute` field names the analytics
function to run after tools finish (`"term_structure" | "skew" | "atm_greeks"`).

## Guardrails

The writer is the only stage that produces user-facing text. It enforces:

1. **No invented numbers.** Every numeric token in `summary` must match a
   value in `numbers_used` within tolerance. Date and option-symbol digits
   are stripped first. Violations raise `GuardrailViolation` rather than
   emitting a misleading answer.
2. **Facts section is mandatory.** Every supported response includes a
   `facts` dict listing the spot price (with timestamp + source), expiries
   used, and the analytics flags from `oqe.analytics`.
3. **Refusal shape.** Not-supported prompts return a labelled refusal plus
   1-3 suggested rewrites that map to supported v1 categories.

## Usage

```python
from oqe.agent import answer_question

resp = answer_question("NVDA ATM IV this week vs next week.")
print(resp.summary)
print(resp.table)
print(resp.facts)
```

Tests can pass a stubbed registry:

```python
from oqe.agent import answer_question, ToolRegistry

registry = ToolRegistry(tools={
    "get_underlying_snapshot": lambda inp: ...,
    "list_option_contracts":   lambda inp: ...,
    "get_option_quotes":       lambda inp: ...,
    "get_option_greeks":       lambda inp: ...,
})
resp = answer_question(prompt, registry=registry)
```
