# Agent internals

For users who want to inspect or replace one stage of the pipeline.

## Modules

```python
from voli.agent import answer_question
from voli.agent.planner import plan, parse_intent
from voli.agent.executor import execute, default_registry, ToolRegistry
from voli.agent.writer import write, GuardrailViolation
from voli.agent.state import AgentState, Intent, Plan, PlanStep, AnswerResponse
```

## State dataclasses

```python
@dataclass
class AgentState:
    prompt: str
    intent: Intent | None = None
    plan: Plan | None = None
    tool_outputs: dict[str, Any] = ...
    metrics: dict[str, Any] = ...
    errors: list[str] = ...
```

```python
@dataclass(frozen=True)
class Intent:
    category: str          # 'chain' | 'term_structure' | 'skew' | 'greeks' | 'not_supported'
    ticker: str | None
    right: str             # 'C' | 'P' | 'BOTH'
    expiry_phrase: str | None
    target_delta: float | None
    not_supported_reason: str | None
    raw_prompt: str
```

```python
@dataclass(frozen=True)
class PlanStep:
    tool: str                           # registered tool name
    inputs: dict[str, Any]              # may contain {"option_symbols_from": "<label>"}
    label: str                          # how the executor keys the output

@dataclass(frozen=True)
class Plan:
    steps: tuple[PlanStep, ...] = ()
    compute: str | None = None          # 'term_structure' | 'skew' | 'atm_greeks' | None
```

## Stepping through the pipeline manually

```python
from voli.agent.executor import default_registry
from voli.agent.planner import plan as plan_stage
from voli.agent.executor import execute as exec_stage
from voli.agent.writer import write as write_stage
from voli.agent.state import AgentState

state = AgentState(prompt="NVDA ATM IV this week vs next week")
state = plan_stage(state)
print("intent:", state.intent.category, state.intent.ticker)
print("plan tools:", [s.tool for s in state.plan.steps])

state = exec_stage(state, registry=default_registry())
print("tool outputs:", list(state.tool_outputs))

resp = write_stage(state)
print(resp.summary)
```

## Planner

The planner is rule-based — regex / keyword classification, no LLM. This
keeps the same prompt → same plan invariant cheap to test.

```python
from voli.agent.planner import parse_intent

intent = parse_intent("Show NVDA IV skew next Friday")
# Intent(category='skew', ticker='NVDA', right='BOTH', expiry_phrase='next_friday', ...)
```

Categories and the keywords that drive each are documented in the
[Orchestrator architecture](../architecture/orchestrator.md) page.

## Executor + ToolRegistry

The executor is tool-agnostic — it dispatches to a `ToolRegistry`. Tests
inject stub registries; production uses `default_registry()`.

```python
from voli.agent.executor import ToolRegistry

# A registry is just a dict of tool name -> callable.
reg = ToolRegistry(tools={
    "get_underlying_snapshot": my_underlying_fn,
    "list_option_contracts":   my_contracts_fn,
    "get_option_quotes":       my_quotes_fn,
    "get_option_greeks":       my_greeks_fn,
})
```

Each callable takes a dict of inputs and returns an object with whichever
of `.snapshot`, `.contracts`, `.quotes`, `.greeks` it's responsible for.
Mirror the shape of `voli.tool_schemas.GetXOutput` types.

## Writer

The writer renders the final `AnswerResponse` and enforces guardrails:

- Every numeric token in `summary` must match a value in `numbers_used`
  within `1e-4` tolerance (ISO dates and option symbols are stripped first).
- Failure raises `voli.agent.writer.GuardrailViolation` rather than emit a
  misleading answer.

You shouldn't normally interact with the writer directly — `answer_question`
calls it for you.

## See also

- [Architecture: orchestrator flow](../architecture/orchestrator.md)
- [Architecture: guardrails](../architecture/guardrails.md)
