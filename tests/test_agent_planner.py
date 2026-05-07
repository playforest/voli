"""Planner-only tests: prompt -> Intent -> Plan.

We assert category, ticker, right, and the exact tool sequence the planner
emits. The Polygon tools are never called here.
"""

from __future__ import annotations

import pytest

from voli.agent.planner import _build_plan, parse_intent, plan
from voli.agent.state import AgentState


@pytest.mark.parametrize(
    "prompt,expected_category,expected_ticker",
    [
        ("Show NVDA options expiring this Friday, strikes within +/-5% of spot.", "chain", "NVDA"),
        ("List NVDA calls for 2026-01-16 between 120 and 150.", "chain", "NVDA"),
        ("NVDA ATM IV this week vs next week.", "term_structure", "NVDA"),
        ("Compare ATM IV for SPY front week, next week, and next month.", "term_structure", "SPY"),
        ("Show NVDA IV skew for next Friday, ±10 strikes around ATM.", "skew", "NVDA"),
        ("Compute 25d put IV vs 25d call IV for SPY next month.", "skew", "SPY"),
        ("What are the greeks of the NVDA 2026-01-16 130C?", "greeks", "NVDA"),
        (
            "Show delta/gamma/theta/vega for the 5 strikes around ATM for SPY this Friday.",
            "greeks",
            "SPY",
        ),
        ("Should I buy NVDA calls?", "not_supported", "NVDA"),
        ("Why did SPY IV go up?", "not_supported", "SPY"),
        ("Predict NVDA price target.", "not_supported", "NVDA"),
        ("Manage my QQQ portfolio.", "not_supported", "QQQ"),
    ],
)
def test_classification(prompt: str, expected_category: str, expected_ticker: str) -> None:
    intent = parse_intent(prompt)
    assert intent.category == expected_category
    assert intent.ticker == expected_ticker


def test_right_inference() -> None:
    assert parse_intent("List NVDA calls for 2026-01-16 between 120 and 150.").right == "C"
    assert parse_intent("List SPY puts for the next monthly expiry.").right == "P"
    # When both calls and puts mentioned, default BOTH.
    assert parse_intent("Show NVDA calls and puts.").right == "BOTH"
    assert parse_intent("ATM IV for QQQ.").right == "BOTH"


def test_target_delta_extraction() -> None:
    assert parse_intent("Compute 25d put IV vs 25d call IV.").target_delta == 0.25
    assert parse_intent("Compute 10 delta risk reversal.").target_delta == 0.10


def test_explicit_iso_date_in_contract_inputs() -> None:
    intent = parse_intent("List NVDA calls for 2026-01-16 between 120 and 150.")
    p = _build_plan(intent)
    assert p.steps[1].tool == "list_option_contracts"
    assert p.steps[1].inputs["expiry"] == "2026-01-16"
    assert p.steps[1].inputs["right"] == "C"


def test_chain_plan_shape() -> None:
    intent = parse_intent("Show NVDA options expiring this Friday.")
    p = _build_plan(intent)
    assert [s.tool for s in p.steps] == [
        "get_underlying_snapshot",
        "list_option_contracts",
        "get_option_quotes",
    ]
    assert p.compute is None


def test_term_structure_plan_shape() -> None:
    intent = parse_intent("NVDA ATM IV this week vs next week.")
    p = _build_plan(intent)
    assert [s.tool for s in p.steps] == [
        "get_underlying_snapshot",
        "list_option_contracts",
        "get_option_greeks",
    ]
    assert p.compute == "term_structure"


def test_skew_plan_shape() -> None:
    intent = parse_intent("Show NVDA IV skew for next Friday.")
    p = _build_plan(intent)
    assert [s.tool for s in p.steps] == [
        "get_underlying_snapshot",
        "list_option_contracts",
        "get_option_quotes",
        "get_option_greeks",
    ]
    assert p.compute == "skew"


def test_greeks_plan_shape() -> None:
    intent = parse_intent("What are the greeks of the NVDA 2026-01-16 130C?")
    p = _build_plan(intent)
    assert [s.tool for s in p.steps] == [
        "get_underlying_snapshot",
        "list_option_contracts",
        "get_option_greeks",
    ]
    assert p.compute == "atm_greeks"


def test_not_supported_skips_plan() -> None:
    state = plan(AgentState(prompt="Should I sell NVDA calls?"))
    assert state.intent is not None
    assert state.intent.category == "not_supported"
    assert state.plan is not None
    assert state.plan.steps == ()


def test_missing_ticker_records_error() -> None:
    state = plan(AgentState(prompt="Show options expiring this Friday."))
    assert "MISSING_TICKER" in state.errors


def test_ticker_default_used_when_prompt_lacks_ticker() -> None:
    state = plan(
        AgentState(prompt="Show options expiring this Friday."),
        ticker_default="NVDA",
    )
    assert state.intent is not None
    assert state.intent.ticker == "NVDA"
    assert "MISSING_TICKER" not in state.errors
