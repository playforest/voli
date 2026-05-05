"""Data model that flows through the planner -> executor -> writer pipeline.

The orchestrator never mutates `Intent` or `Plan` after the planner stage;
the executor accumulates `tool_outputs` and `metrics`; the writer reads
the final state and produces an `AnswerResponse`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# Question categories from docs/requirements.md.
Category = Literal[
    "chain",
    "term_structure",
    "skew",
    "greeks",
    "not_supported",
]

Right = Literal["C", "P", "BOTH"]

NotSupportedReason = Literal[
    "advice",
    "execution",
    "news",
    "portfolio",
    "strategy",
    "prediction",
]


@dataclass(frozen=True)
class Intent:
    """Structured representation of what the user asked for.

    Produced by the planner; consumed by every later stage.
    """

    category: Category
    ticker: str | None
    right: Right = "BOTH"
    expiry_phrase: str | None = None  # e.g. "this_week", "next_week", "front_monthly", iso date
    target_delta: float | None = None  # e.g. 0.25 for 25-delta skew
    not_supported_reason: NotSupportedReason | None = None
    raw_prompt: str = ""


@dataclass(frozen=True)
class PlanStep:
    """A single tool invocation, fully specified by the planner."""

    tool: str  # name registered in the executor's ToolRegistry
    inputs: dict[str, Any]
    label: str  # short identifier the executor uses to key the output


@dataclass(frozen=True)
class Plan:
    """Ordered list of tool steps the executor must run.

    `compute` is a single optional analytics step name (one of "term_structure",
    "skew", "atm_greeks", or None). Analytics computation is centralized in
    `oqe.analytics`; the agent does not invent numbers itself.
    """

    steps: tuple[PlanStep, ...] = ()
    compute: str | None = None


@dataclass
class AgentState:
    """Mutable container threaded through the pipeline.

    Each stage adds fields; we never overwrite previous ones.
    """

    prompt: str
    intent: Intent | None = None
    plan: Plan | None = None
    tool_outputs: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AnswerResponse:
    """What the writer returns. Designed for both CLI and JSON consumers.

    `numbers_used` is the *complete* list of numeric values the writer is allowed
    to reference in `summary`. The guardrail enforces that no other numbers leak
    in.
    """

    supported: bool
    category: Category
    summary: str
    table: dict[str, Any]
    facts: dict[str, Any]
    numbers_used: list[float]
    limitations: list[str] = field(default_factory=list)
    suggested_rewrites: list[str] = field(default_factory=list)
