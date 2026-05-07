# Orchestrator flow

A small deterministic state machine. Every prompt walks the same four
stages, so behaviour is predictable and trivially testable.

```
prompt
  -> planner   (Intent + Plan)
  -> executor  (tool outputs + computed metrics)
  -> writer    (themed AnswerResponse)
  -> rendered  (CLI prints text or JSON)
```

## Stage 1 — planner

`voli.agent.planner` parses the prompt with regex / keyword rules — no LLM.

Outputs:

- `Intent`: category, ticker, right (`C`/`P`/`BOTH`), expiry phrase,
  target delta, plus a `not_supported_reason` if the prompt is out of
  scope.
- `Plan`: ordered tuple of `PlanStep`s and an optional `compute` step.

Why rule-based:

- Same prompt → same plan, every run.
- Tests need no model / network.
- The "no invented numbers" guarantee is easier to audit when the planner
  is a pure function.

A future Part 6.x could swap this for an LLM-backed planner that produces
the same `Intent` / `Plan` shape; the rest of the pipeline doesn't change.

## Stage 2 — executor

`voli.agent.executor.execute()` runs each `PlanStep` against a `ToolRegistry`.

- The default registry wires the real Polygon-backed tools.
- Tests pass a stubbed registry (or the synthetic one from
  `voli.eval.synth_market`).
- Late-bound inputs (e.g. quotes need the contracts list) are resolved
  before each step runs.

If `Plan.compute` is set, the executor calls
`voli.analytics.compute_v1_metrics_bundle()` and stashes the result on
`AgentState.metrics`. Centralising this means the writer never derives
new numbers itself — the guardrail has nothing to enforce against if it
did.

## Stage 3 — writer

`voli.agent.writer.write()` chooses a renderer per category and produces
an `AnswerResponse`.

It enforces two contract guardrails on every supported response:

1. **No invented numbers.** Every numeric token in `summary` must match a
   value in `numbers_used` within `1e-4`. Failures raise
   `GuardrailViolation` rather than emit a misleading answer.
2. **Facts is mandatory.** Spot value/timestamp/source, expiries, right
   filter, and analytics flags must be present.

Refusals + missing-ticker get their own renderers that produce no table
but include `suggested_rewrites`.

## Stage 4 — render

`voli.cli_render.render_response()` (themed text) or `render_json()`
(machine-readable) emits the final string. The CLI handles stdout.

## Diagram

``` mermaid
flowchart TD
  P[prompt] --> Plan(planner)
  Plan -->|Intent + Plan| Exec(executor)
  Exec -->|tool outputs| Analytics{compute step?}
  Analytics -- yes --> Bundle(compute_v1_metrics_bundle)
  Analytics -- no --> W(writer)
  Bundle --> W
  W -->|AnswerResponse| Render(cli_render)
  Render --> Out[stdout]
```

## State dataclass

The whole pipeline threads one mutable `AgentState`:

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

Each stage adds fields; we never overwrite previous ones. This makes
debug-printing the state at any boundary safe and informative.

## Where to look

| Concern | Module |
| --- | --- |
| Prompt → category classification | `voli/agent/planner.py` |
| Tool dispatch + plan execution | `voli/agent/executor.py` |
| Per-category rendering + guardrails | `voli/agent/writer.py` |
| Dataclasses (Intent / Plan / AgentState) | `voli/agent/state.py` |
| Analytics (term structure / skew / greeks) | `voli/analytics/` |
| Polygon tool implementations | `voli/tools/polygon_tools.py` |
| Themed renderer | `voli/cli_render.py` |

## See also

- [Data model](data-model.md) — Pydantic models the executor returns.
- [Caching](caching.md) — how the same prompt becomes deterministic.
- [Guardrails](guardrails.md) — the writer's enforcement details.
