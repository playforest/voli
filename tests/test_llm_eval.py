"""LLM-as-judge eval harness tests.

We can't drive a real LLM here (cost, nondeterminism), so we use stub
providers that script their step() outputs. The reference fetcher is
patched to use the synthetic registry so every case runs offline.
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from oqe.eval.llm_runner import (
    LLMEvalCase,
    _parse_judge_response,
    default_dataset_path,
    evaluate_case,
    load_cases,
    main,
    render_report,
    render_report_json,
    run_eval,
)
from oqe.llm import LLMProvider, StepComplete, TextDelta, ToolCallStart, ToolResult

# ----------------------------------------------------------------------------
# Stub providers
# ----------------------------------------------------------------------------


@dataclass
class _StubSUT(LLMProvider):
    """SUT stub: emits a tool call (echoed back) then a fixed answer."""

    answer: str = "Front IV is 0.30, next IV is 0.35, ATM strike is 100.0."
    name: str = "stub"
    model: str = "stub-sut"
    _step: int = 0

    def start(self, *, system, tools, user_message, max_tokens=2048, temperature=0.2):
        self._step = 0

    def step(self) -> Iterator[Any]:
        if self._step == 0:
            self._step += 1
            yield ToolCallStart(
                id="t1",
                name="compute_atm_iv_term_structure",
                arguments={"ticker": "NVDA"},
            )
            yield StepComplete(stop_reason="tool_use")
        else:
            yield TextDelta(text=self.answer)
            yield StepComplete(stop_reason="end_turn")

    def submit_tool_results(self, results: list[ToolResult]) -> None:
        pass


@dataclass
class _StubJudge(LLMProvider):
    """Judge stub: emits a fixed verdict + reasoning."""

    verdict: str = "PASS"
    reasoning: str = "matches reference within tolerance."
    name: str = "stub"
    model: str = "stub-judge"
    captured_user_message: str = ""

    def start(self, *, system, tools, user_message, max_tokens=2048, temperature=0.2):
        self.captured_user_message = user_message

    def step(self) -> Iterator[Any]:
        yield TextDelta(text=f"VERDICT: {self.verdict}\nREASONING: {self.reasoning}\n")
        yield StepComplete(stop_reason="end_turn")

    def submit_tool_results(self, results) -> None:
        pass


@pytest.fixture()
def patched_reference(monkeypatch):
    """Replace the analytics tool's chain fetcher with the synthetic
    registry so reference fetches stay offline.
    """

    from oqe.eval.synth_market import make_registry

    reg = make_registry()
    list_contracts = reg.tools["list_option_contracts"]
    quotes = reg.tools["get_option_quotes"]
    greeks = reg.tools["get_option_greeks"]
    underlying = reg.tools["get_underlying_snapshot"]

    def _to_dict(model):
        if hasattr(model, "model_dump"):
            return model.model_dump(mode="json", exclude_none=True)
        return dict(model)

    monkeypatch.setattr(
        "oqe.llm.analytics_tools.get_underlying_snapshot",
        lambda inp: underlying(_to_dict(inp)),
    )

    def _fake_bulk(ticker, *, right=None, expiry=None, max_pages=20):
        list_args: dict[str, object] = {"ticker": ticker, "limit": 500}
        if right is not None:
            list_args["right"] = right
        if expiry is not None:
            list_args["expiry"] = expiry
        contracts_resp = list_contracts(list_args)
        contracts = list(contracts_resp.contracts)
        if not contracts:
            return [], {}, {}
        symbols = [c.option_symbol for c in contracts]
        q_resp = quotes({"option_symbols": symbols})
        g_resp = greeks({"option_symbols": symbols})
        return (
            contracts,
            {q.option_symbol: q for q in q_resp.quotes},
            {g.option_symbol: g for g in g_resp.greeks},
        )

    monkeypatch.setattr("oqe.llm.analytics_tools.get_option_chain_bulk", _fake_bulk)
    return reg


# ----------------------------------------------------------------------------
# Dataset
# ----------------------------------------------------------------------------


def test_default_dataset_loads_30_cases() -> None:
    cases = load_cases(default_dataset_path())
    assert len(cases) == 30
    cats = {c.category for c in cases}
    assert cats == {"term_structure", "skew", "greeks"}


def test_dataset_path_lives_under_repo_root() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    assert default_dataset_path() == repo_root / "eval" / "llm_prompts.jsonl"


def test_every_case_has_a_known_reference_tool() -> None:
    """Every reference_tool in the dataset must be one the runner knows
    how to dispatch - otherwise that case will always ERROR.
    """

    from oqe.eval.llm_runner import REFERENCE_FETCHERS

    for case in load_cases(default_dataset_path()):
        assert case.reference_tool in REFERENCE_FETCHERS, (
            f"{case.id}: unknown reference_tool {case.reference_tool!r}"
        )


# ----------------------------------------------------------------------------
# Judge response parsing
# ----------------------------------------------------------------------------


def test_parse_judge_pass() -> None:
    verdict, reasoning = _parse_judge_response(
        "VERDICT: PASS\nREASONING: matches the reference within tolerance."
    )
    assert verdict == "PASS"
    assert "tolerance" in reasoning


def test_parse_judge_fail() -> None:
    verdict, reasoning = _parse_judge_response(
        "VERDICT: FAIL\nREASONING: front IV off by 2 vol points."
    )
    assert verdict == "FAIL"
    assert "off by" in reasoning


def test_parse_judge_handles_lowercase_and_whitespace() -> None:
    verdict, _ = _parse_judge_response("\n  verdict: pass\n  reasoning: ok.")
    assert verdict == "PASS"


def test_parse_judge_unparseable_returns_error() -> None:
    verdict, reasoning = _parse_judge_response("nonsense response with no verdict")
    assert verdict == "ERROR"
    assert "could not parse" in reasoning


# ----------------------------------------------------------------------------
# evaluate_case
# ----------------------------------------------------------------------------


def test_evaluate_case_pass(patched_reference) -> None:
    case = LLMEvalCase(
        id="tc_1",
        prompt="What's NVDA's ATM IV term structure?",
        category="term_structure",
        reference_tool="compute_atm_iv_term_structure",
        reference_args={"ticker": "NVDA"},
        rubric_hint="Within 0.5 vol points / $1.",
    )
    result = evaluate_case(
        case,
        sut_provider=_StubSUT(),
        judge_provider=_StubJudge(verdict="PASS", reasoning="ok"),
    )
    assert result.verdict == "PASS"
    assert result.reasoning == "ok"
    assert result.sut_tool_calls == 1
    # Reference was fetched (non-empty JSON).
    payload = json.loads(result.reference_data)
    assert payload["ticker"] == "NVDA"
    assert payload["front_iv"] == pytest.approx(0.30, abs=1e-6)


def test_evaluate_case_fail(patched_reference) -> None:
    case = LLMEvalCase(
        id="tc_2",
        prompt="QQQ ATM IV?",
        category="term_structure",
        reference_tool="compute_atm_iv_term_structure",
        reference_args={"ticker": "QQQ"},
        rubric_hint="Within 0.5 vol points.",
    )
    result = evaluate_case(
        case,
        sut_provider=_StubSUT(),
        judge_provider=_StubJudge(verdict="FAIL", reasoning="off by 2 vols"),
    )
    assert result.verdict == "FAIL"
    assert "off by" in result.reasoning


def test_evaluate_case_unknown_reference_tool() -> None:
    case = LLMEvalCase(
        id="tc_x",
        prompt="x",
        category="term_structure",
        reference_tool="not_a_tool",
        reference_args={},
        rubric_hint="",
    )
    result = evaluate_case(
        case,
        sut_provider=_StubSUT(),
        judge_provider=_StubJudge(),
    )
    assert result.verdict == "ERROR"
    assert "unknown reference_tool" in result.reasoning


def test_evaluate_case_judge_sees_reference_and_sut(patched_reference) -> None:
    """Confirm the judge user-message includes both pieces of context so
    we know it actually had the data to grade against.
    """

    judge = _StubJudge(verdict="PASS", reasoning="ok")
    case = LLMEvalCase(
        id="tc_3",
        prompt="What's NVDA's ATM IV?",
        category="term_structure",
        reference_tool="compute_atm_iv_term_structure",
        reference_args={"ticker": "NVDA"},
        rubric_hint="Within 0.5 vol points.",
    )
    evaluate_case(case, sut_provider=_StubSUT(), judge_provider=judge)
    msg = judge.captured_user_message
    assert "PROMPT:" in msg
    assert "REFERENCE DATA" in msg
    assert "SUT ANSWER:" in msg
    assert "RUBRIC HINT:" in msg
    assert "NVDA" in msg


# ----------------------------------------------------------------------------
# run_eval / report
# ----------------------------------------------------------------------------


def test_run_eval_with_limit(patched_reference) -> None:
    report = run_eval(
        sut_provider=_StubSUT(),
        judge_provider=_StubJudge(verdict="PASS", reasoning="ok"),
        limit=3,
    )
    assert report.total == 3
    assert report.passed == 3
    assert report.failed == 0
    assert report.errored == 0


def test_report_renders_with_pass_fail_split(patched_reference) -> None:
    """Build a report by running 2 cases and confirm the themed output
    contains both verdicts and the breakdown.
    """

    # First two cases of the real dataset are both term_structure;
    # script the judge to PASS the first and FAIL the second.
    cases = load_cases(default_dataset_path())[:2]

    @dataclass
    class _AltJudge(_StubJudge):
        _i: int = 0

        def step(self):
            verdicts = ["PASS", "FAIL"]
            verdict = verdicts[min(self._i, len(verdicts) - 1)]
            self._i += 1
            yield TextDelta(text=f"VERDICT: {verdict}\nREASONING: x.\n")
            yield StepComplete(stop_reason="end_turn")

    judge = _AltJudge()
    results = [evaluate_case(c, sut_provider=_StubSUT(), judge_provider=judge) for c in cases]
    from oqe.eval.llm_runner import LLMEvalReport, _group_by_category

    report = LLMEvalReport(results=tuple(results), by_category=_group_by_category(results))
    text = render_report(report, color=False)
    assert "OQE LLM EVAL" in text
    assert "PASS" in text
    assert "FAIL" in text
    assert "term_structure" in text


def test_render_report_json_round_trips(patched_reference) -> None:
    report = run_eval(
        sut_provider=_StubSUT(),
        judge_provider=_StubJudge(verdict="PASS", reasoning="ok"),
        limit=2,
    )
    payload = json.loads(render_report_json(report))
    assert payload["total"] == 2
    assert payload["passed"] == 2
    assert len(payload["cases"]) == 2


# ----------------------------------------------------------------------------
# CLI entry point
# ----------------------------------------------------------------------------


def test_cli_main_with_limit_and_no_color(monkeypatch, patched_reference) -> None:
    """End-to-end: invoke main() with stub providers via monkey-patching
    make_provider, run 2 cases, confirm exit code 0 + themed output.
    """

    monkeypatch.setattr(
        "oqe.eval.llm_runner.make_provider",
        lambda name=None, model=None: (
            _StubJudge(verdict="PASS", reasoning="ok")
            if (model or "").startswith("claude-opus")
            else _StubSUT()
        ),
    )
    out = io.StringIO()
    rc = main(["--no-color", "--limit", "2"], out=out)
    text = out.getvalue()
    assert rc == 0
    assert "OQE LLM EVAL" in text
    assert "2 cases" in text
    assert "2 pass" in text


def test_cli_main_returns_1_when_a_case_fails(monkeypatch, patched_reference) -> None:
    monkeypatch.setattr(
        "oqe.eval.llm_runner.make_provider",
        lambda name=None, model=None: (
            _StubJudge(verdict="FAIL", reasoning="bad")
            if (model or "").startswith("claude-opus")
            else _StubSUT()
        ),
    )
    out = io.StringIO()
    rc = main(["--no-color", "--limit", "1"], out=out)
    assert rc == 1
