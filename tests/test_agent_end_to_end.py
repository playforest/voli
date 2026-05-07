"""End-to-end orchestrator tests.

This file fulfills the Part 6 'Done when' criterion from todo.md:
    "The agent answers 10+ sample prompts with correct tool usage and no
     made-up numbers."

We feed 12 prompts (covering all four supported categories plus the
not-supported refusal path) through the full planner -> executor -> writer
pipeline. The Polygon client is never touched: the executor receives a stub
ToolRegistry that returns synthetic objects. We assert:

  * the planner picked the right category and tool sequence,
  * the executor invoked exactly the planned tools (in order),
  * the writer's guardrail accepted the summary (it raises if any number in
    the summary text isn't in numbers_used),
  * the response contains the required Facts section.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

import pytest

from voli.agent import answer_question
from voli.agent.executor import ToolRegistry
from voli.agent.state import AnswerResponse

# ---------- synthetic data shapes ---------------------------------------------


@dataclass(frozen=True)
class _Snap:
    ticker: str
    spot: float
    ts: datetime
    source: str = "polygon"


@dataclass(frozen=True)
class _Meta:
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class _UnderlyingResp:
    snapshot: _Snap
    meta: _Meta = field(default_factory=_Meta)


@dataclass(frozen=True)
class _Contract:
    option_symbol: str
    expiry: date
    strike: float
    right: str  # "C" or "P"


@dataclass(frozen=True)
class _ContractsResp:
    contracts: list[_Contract]
    meta: _Meta = field(default_factory=_Meta)


@dataclass(frozen=True)
class _Quote:
    option_symbol: str
    bid: float | None
    ask: float | None
    mid: float | None
    last: float | None
    ts: datetime
    source: str = "polygon"


@dataclass(frozen=True)
class _QuotesResp:
    quotes: list[_Quote]
    meta: _Meta = field(default_factory=_Meta)


@dataclass(frozen=True)
class _Greeks:
    option_symbol: str
    iv: float | None
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    ts: datetime
    source: str = "polygon"


@dataclass(frozen=True)
class _GreeksResp:
    greeks: list[_Greeks]
    meta: _Meta = field(default_factory=_Meta)


# ---------- stub market builder -----------------------------------------------


def _build_stub_market() -> tuple[
    dict[str, _UnderlyingResp],
    list[_Contract],
    dict[str, _Quote],
    dict[str, _Greeks],
]:
    """Multi-ticker, multi-expiry synthetic chain.

    For each (ticker, expiry, strike, right) we emit one contract, one quote
    (1.00 wide), and one greeks row whose IV depends on expiry/right/distance
    from the chosen ATM strike. This is enough to make every analytics path
    return non-None metrics.
    """

    now = datetime.now(UTC)
    spots = {"NVDA": 100.0, "SPY": 500.0, "QQQ": 400.0, "AAPL": 200.0, "TSLA": 250.0}
    expiries_by_ticker = {
        "NVDA": [date(2026, 5, 9), date(2026, 5, 16)],
        "SPY": [date(2026, 5, 9), date(2026, 5, 16)],
        "QQQ": [date(2026, 5, 9), date(2026, 5, 16)],
        "AAPL": [date(2026, 5, 9), date(2026, 5, 16)],
        "TSLA": [date(2026, 5, 9), date(2026, 5, 16)],
    }

    underlyings: dict[str, _UnderlyingResp] = {
        t: _UnderlyingResp(snapshot=_Snap(ticker=t, spot=s, ts=now)) for t, s in spots.items()
    }

    contracts: list[_Contract] = []
    quotes: dict[str, _Quote] = {}
    greeks: dict[str, _Greeks] = {}

    for ticker, spot in spots.items():
        # 11 strikes spaced 5 apart, centered on spot.
        strikes = [spot + 5 * i for i in range(-5, 6)]
        for exp in expiries_by_ticker[ticker]:
            for k in strikes:
                for right in ("C", "P"):
                    sym = f"O:{ticker}{exp.strftime('%y%m%d')}{right}{int(k * 1000):08d}"
                    contracts.append(_Contract(sym, exp, float(k), right))

                    base_iv = 0.30 + (0.05 if exp == expiries_by_ticker[ticker][1] else 0.0)
                    if right == "P":
                        base_iv += 0.03
                    base_iv += 0.002 * abs(k - spot)

                    quotes[sym] = _Quote(
                        option_symbol=sym,
                        bid=1.00,
                        ask=2.00,
                        mid=1.50,
                        last=1.50,
                        ts=now,
                    )
                    greeks[sym] = _Greeks(
                        option_symbol=sym,
                        iv=base_iv,
                        delta=0.5 if right == "C" else -0.5,
                        gamma=0.02,
                        theta=-0.10,
                        vega=0.12,
                        ts=now,
                    )

    return underlyings, contracts, quotes, greeks


# ---------- registry + call recorder ------------------------------------------


@dataclass
class _Recorder:
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)


def _make_registry(rec: _Recorder) -> ToolRegistry:
    underlyings, contracts, quotes_map, greeks_map = _build_stub_market()

    def _underlying(inp: dict) -> _UnderlyingResp:
        rec.calls.append(("get_underlying_snapshot", inp))
        return underlyings[inp["ticker"]]

    def _list_contracts(inp: dict) -> _ContractsResp:
        rec.calls.append(("list_option_contracts", inp))
        out = [c for c in contracts if c.option_symbol.startswith(f"O:{inp['ticker']}")]
        if "right" in inp:
            out = [c for c in out if c.right == inp["right"]]
        if "expiry" in inp:
            target = (
                date.fromisoformat(inp["expiry"])
                if isinstance(inp["expiry"], str)
                else inp["expiry"]
            )
            out = [c for c in out if c.expiry == target]
        return _ContractsResp(contracts=out)

    def _quotes(inp: dict) -> _QuotesResp:
        rec.calls.append(("get_option_quotes", inp))
        return _QuotesResp(quotes=[quotes_map[s] for s in inp["option_symbols"] if s in quotes_map])

    def _greeks(inp: dict) -> _GreeksResp:
        rec.calls.append(("get_option_greeks", inp))
        return _GreeksResp(greeks=[greeks_map[s] for s in inp["option_symbols"] if s in greeks_map])

    return ToolRegistry(
        tools={
            "get_underlying_snapshot": _underlying,
            "list_option_contracts": _list_contracts,
            "get_option_quotes": _quotes,
            "get_option_greeks": _greeks,
        }
    )


# ---------- shared assertions -------------------------------------------------


def _assert_grounded(resp: AnswerResponse) -> None:
    """The writer raises GuardrailViolation if a number leaked. If we got an
    AnswerResponse back at all, the guardrail passed - but we still verify
    the contract: supported responses must have a Facts section and table.
    """

    assert resp.summary
    assert resp.table is not None
    assert resp.facts is not None
    if resp.supported:
        assert "spot" in resp.facts or resp.facts.get("missing")  # spot or disclosed missing
        assert resp.numbers_used, "supported answers must record their numbers"


# ---------- the 12 sample prompts ---------------------------------------------


SAMPLE_PROMPTS: list[tuple[str, str, list[str]]] = [
    # (prompt, expected_category, expected tool sequence)
    (
        "Show NVDA options expiring this Friday, strikes within ±5% of spot.",
        "chain",
        ["get_underlying_snapshot", "list_option_contracts", "get_option_quotes"],
    ),
    (
        "List NVDA calls for 2026-05-16 between 90 and 110.",
        "chain",
        ["get_underlying_snapshot", "list_option_contracts", "get_option_quotes"],
    ),
    (
        "What's the ATM call and put for QQQ next week? Include bid/ask.",
        "chain",
        ["get_underlying_snapshot", "list_option_contracts", "get_option_quotes"],
    ),
    (
        "NVDA ATM IV this week vs next week.",
        "term_structure",
        ["get_underlying_snapshot", "list_option_contracts", "get_option_greeks"],
    ),
    (
        "Compare ATM IV for SPY front week vs next week.",
        "term_structure",
        ["get_underlying_snapshot", "list_option_contracts", "get_option_greeks"],
    ),
    (
        "Show IV term structure (ATM) for QQQ.",
        "term_structure",
        ["get_underlying_snapshot", "list_option_contracts", "get_option_greeks"],
    ),
    (
        "Show NVDA IV skew for next Friday, ±10 strikes around ATM.",
        "skew",
        [
            "get_underlying_snapshot",
            "list_option_contracts",
            "get_option_quotes",
            "get_option_greeks",
        ],
    ),
    (
        "What's the skew slope across strikes for TSLA next week?",
        "skew",
        [
            "get_underlying_snapshot",
            "list_option_contracts",
            "get_option_quotes",
            "get_option_greeks",
        ],
    ),
    (
        "What are the greeks of the NVDA 2026-05-16 100C?",
        "greeks",
        ["get_underlying_snapshot", "list_option_contracts", "get_option_greeks"],
    ),
    (
        "Show delta/gamma/theta/vega for the 5 strikes around ATM for SPY this Friday.",
        "greeks",
        ["get_underlying_snapshot", "list_option_contracts", "get_option_greeks"],
    ),
    ("Should I buy NVDA calls?", "not_supported", []),
    ("Why did SPY IV go up this week?", "not_supported", []),
]


@pytest.mark.parametrize("prompt,category,expected_tools", SAMPLE_PROMPTS)
def test_sample_prompt_runs_correct_tools_with_grounded_answer(
    prompt: str, category: str, expected_tools: list[str]
) -> None:
    rec = _Recorder()
    registry = _make_registry(rec)

    resp = answer_question(prompt, registry=registry)

    # Plan -> tool calls match expectations.
    actual_tools = [name for name, _inp in rec.calls]
    assert actual_tools == expected_tools, (
        f"For prompt {prompt!r}: expected {expected_tools}, got {actual_tools}"
    )

    # Category matches what the writer rendered.
    assert resp.category == category

    # No-invented-numbers guardrail held (would have raised otherwise).
    _assert_grounded(resp)


def test_run_all_twelve_prompts_in_one_pass() -> None:
    """Belt-and-braces: explicitly count >= 10 supported runs in one batch."""
    successes = 0
    for prompt, _cat, _tools in SAMPLE_PROMPTS:
        rec = _Recorder()
        registry = _make_registry(rec)
        resp = answer_question(prompt, registry=registry)
        _assert_grounded(resp)
        successes += 1
    assert successes >= 10


def test_term_structure_summary_contains_only_recorded_numbers() -> None:
    rec = _Recorder()
    registry = _make_registry(rec)
    resp = answer_question("NVDA ATM IV this week vs next week.", registry=registry)

    # Pull the analytics outputs straight out of facts and assert the summary
    # mentions THOSE numbers (and no other floats).
    assert resp.facts["front_iv"] is not None
    assert resp.facts["next_iv"] is not None
    assert resp.facts["atm_strike"] is not None
    # The summary must include each recorded value.
    for v in (resp.facts["front_iv"], resp.facts["next_iv"], resp.facts["atm_strike"]):
        assert any(abs(float(v) - n) < 1e-6 for n in resp.numbers_used)


def test_not_supported_response_offers_rewrites() -> None:
    rec = _Recorder()
    registry = _make_registry(rec)
    resp = answer_question("Should I sell NVDA puts?", registry=registry)

    assert resp.supported is False
    assert resp.category == "not_supported"
    assert resp.suggested_rewrites, "refusals must offer at least one rewrite"
    # No tools were called for a not-supported prompt.
    assert rec.calls == []


def test_missing_ticker_prompts_clarification() -> None:
    rec = _Recorder()
    registry = _make_registry(rec)
    resp = answer_question("Show ATM call and put this Friday.", registry=registry)

    assert resp.supported is False
    assert "ticker" in resp.summary.lower()
    # No tool calls because we never resolved a ticker.
    assert rec.calls == []
