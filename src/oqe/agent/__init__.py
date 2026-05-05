"""Agent orchestration: planner -> executor -> writer.

`answer_question` is the single public entrypoint.
"""

from __future__ import annotations

from .executor import ToolRegistry, default_registry, execute
from .planner import plan
from .state import AgentState, AnswerResponse, Intent, Plan, PlanStep
from .writer import write

__all__ = [
    "AgentState",
    "AnswerResponse",
    "Intent",
    "Plan",
    "PlanStep",
    "ToolRegistry",
    "answer_question",
    "default_registry",
    "execute",
    "plan",
    "write",
]


def answer_question(
    prompt: str,
    *,
    ticker_default: str | None = None,
    registry: ToolRegistry | None = None,
) -> AnswerResponse:
    """Run the full planner -> executor -> writer pipeline.

    `registry` is the tool registry. Tests inject stubs; production code uses
    `default_registry()`.
    """

    state = AgentState(prompt=prompt)
    state = plan(state, ticker_default=ticker_default)
    state = execute(state, registry=registry or default_registry())
    return write(state)
