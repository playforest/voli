"""Executor: runs the Plan against a ToolRegistry and computes metrics.

The executor is intentionally tool-agnostic. The default registry wires the
real Polygon-backed tools from `voli.tools.polygon_tools`, but tests inject
stub callables that return synthetic objects with the same attribute shapes
(option_symbol, strike, right, expiry, iv, delta, ...). This decouples the
agent layer from network I/O and keeps end-to-end tests deterministic.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from voli.analytics.iv_metrics import normalize_right
from voli.analytics.metrics_bundle import compute_v1_metrics_bundle

from .state import AgentState, Plan, PlanStep

ToolFn = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True)
class ToolRegistry:
    """Maps tool name -> callable. Each callable accepts a dict of inputs and
    returns a value with `.snapshot`, `.contracts`, `.quotes`, or `.greeks`
    attributes (whichever applies). The shape mirrors what the polygon tools
    already return.
    """

    tools: dict[str, ToolFn] = field(default_factory=dict)

    def get(self, name: str) -> ToolFn:
        try:
            return self.tools[name]
        except KeyError as exc:
            raise KeyError(f"No tool registered for '{name}'") from exc


def default_registry() -> ToolRegistry:
    """Build the production registry that calls the real Polygon-backed tools.

    Imports are local so unit tests that stub the registry don't pull in the
    Polygon client (which would force httpx + an API key into the test path).
    """

    from voli.tool_schemas import (
        GetOptionGreeksInput,
        GetOptionQuotesInput,
        GetUnderlyingSnapshotInput,
        ListOptionContractsInput,
    )
    from voli.tools.polygon_tools import (
        get_option_greeks,
        get_option_quotes,
        get_underlying_snapshot,
        list_option_contracts,
    )

    def _underlying(inputs: dict[str, Any]) -> Any:
        return get_underlying_snapshot(GetUnderlyingSnapshotInput(**inputs))

    def _contracts(inputs: dict[str, Any]) -> Any:
        return list_option_contracts(ListOptionContractsInput(**inputs))

    def _quotes(inputs: dict[str, Any]) -> Any:
        return get_option_quotes(GetOptionQuotesInput(**inputs))

    def _greeks(inputs: dict[str, Any]) -> Any:
        return get_option_greeks(GetOptionGreeksInput(**inputs))

    return ToolRegistry(
        tools={
            "get_underlying_snapshot": _underlying,
            "list_option_contracts": _contracts,
            "get_option_quotes": _quotes,
            "get_option_greeks": _greeks,
        }
    )


def _resolve_inputs(step: PlanStep, outputs: dict[str, Any]) -> dict[str, Any]:
    """Replace late-bound input shorthand with values from upstream outputs.

    The planner doesn't know the option symbols ahead of time, so it writes
    {"option_symbols_from": "contracts"} and the executor swaps in the real
    list once `contracts` has run.
    """

    resolved = dict(step.inputs)
    src = resolved.pop("option_symbols_from", None)
    if src is not None:
        upstream = outputs.get(src)
        if upstream is None:
            raise RuntimeError(f"Step '{step.label}' depends on '{src}' which has not run")
        contracts = getattr(upstream, "contracts", None) or []
        resolved["option_symbols"] = [c.option_symbol for c in contracts]
    return resolved


def _run_plan(plan: Plan, registry: ToolRegistry) -> dict[str, Any]:
    outputs: dict[str, Any] = {}
    for step in plan.steps:
        inputs = _resolve_inputs(step, outputs)
        if step.tool == "get_option_quotes" and not inputs.get("option_symbols"):
            # Skip empty fan-out cleanly rather than letting Pydantic raise.
            outputs[step.label] = _Empty(quotes=[])
            continue
        if step.tool == "get_option_greeks" and not inputs.get("option_symbols"):
            outputs[step.label] = _Empty(greeks=[])
            continue
        outputs[step.label] = registry.get(step.tool)(inputs)
    return outputs


@dataclass(frozen=True)
class _Empty:
    quotes: list = field(default_factory=list)
    greeks: list = field(default_factory=list)


def _compute_metrics(state: AgentState, outputs: dict[str, Any]) -> dict[str, Any]:
    """Apply the analytics function indicated by `plan.compute`.

    Centralizing this here means the writer only consumes already-computed
    numbers - it never derives new ones, which keeps the
    "no invented numbers" guardrail simple to enforce.
    """

    plan = state.plan
    intent = state.intent
    if plan is None or intent is None or plan.compute is None:
        return {}

    spot_obj = outputs.get("spot")
    contracts_obj = outputs.get("contracts")
    if spot_obj is None or contracts_obj is None:
        return {}

    spot = spot_obj.snapshot.spot
    contracts = list(contracts_obj.contracts)
    greeks_list = list(getattr(outputs.get("greeks"), "greeks", []) or [])
    greeks_by_symbol = {g.option_symbol: g for g in greeks_list}
    quotes_list = list(getattr(outputs.get("quotes"), "quotes", []) or [])
    quotes_by_symbol = {q.option_symbol: q for q in quotes_list}

    right = "call" if intent.right in ("C", "BOTH") else "put"
    bundle = compute_v1_metrics_bundle(
        spot=spot,
        contracts=contracts,
        greeks_by_symbol=greeks_by_symbol,
        right=right,
        quotes_by_symbol=quotes_by_symbol or None,
    )

    return {"bundle": bundle, "right_used": normalize_right(right), "spot": spot}


def execute(state: AgentState, *, registry: ToolRegistry) -> AgentState:
    """Stage 2: run the plan and (if requested) compute analytics."""

    if state.plan is None or state.intent is None:
        return state
    if state.intent.category == "not_supported" or state.intent.ticker is None:
        return state

    outputs = _run_plan(state.plan, registry)
    state.tool_outputs = outputs
    state.metrics = _compute_metrics(state, outputs)
    return state
