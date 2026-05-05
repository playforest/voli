"""Agent orchestration: planner -> executor -> writer (-> skeptic).

`answer_question` is the single public entrypoint.
"""

from __future__ import annotations

from dataclasses import replace

from .executor import ToolRegistry, default_registry, execute
from .planner import plan
from .skeptic import SkepticConcern, review
from .state import AgentState, AnswerResponse, Intent, Plan, PlanStep
from .writer import write

__all__ = [
    "AgentState",
    "AnswerResponse",
    "Intent",
    "Plan",
    "PlanStep",
    "SkepticConcern",
    "ToolRegistry",
    "answer_question",
    "default_registry",
    "execute",
    "plan",
    "review",
    "write",
]


def answer_question(
    prompt: str,
    *,
    ticker_default: str | None = None,
    registry: ToolRegistry | None = None,
    skeptic: bool = False,
) -> AnswerResponse:
    """Run the full planner -> executor -> writer pipeline.

    `registry` is the tool registry. Tests inject stubs; production code uses
    `default_registry()`.

    `skeptic=True` runs the skeptic sub-agent after the writer and attaches
    its concerns to the response. Default `False` for backward compatibility
    (the existing eval / tests don't expect a skeptic block).
    """

    state = AgentState(prompt=prompt)
    state = plan(state, ticker_default=ticker_default)
    state = execute(state, registry=registry or default_registry())
    response = write(state)

    if skeptic:
        concerns = review(response, tool_outputs=state.tool_outputs)
        response = replace(response, skeptic=[c.render() for c in concerns])

    return response
