"""LLM-as-judge evaluation harness.

Per case (loaded from `eval/llm_prompts.jsonl`):

  1. **Reference** — the harness fetches ground-truth data by calling
     Voli's analytics tool directly (no LLM in the loop). This is the
     "oracle" the SUT will be graded against.
  2. **System Under Test (SUT)** — the LLM agent (`voli.llm.llm_ask`)
     answers the prompt using the Voli MCP-style tool surface. We
     capture both the synthesised answer text and the tool-call log.
  3. **Judge** — a separate, stronger LLM is given the prompt + the
     reference data + the SUT's answer + a rubric. It returns a
     PASS/FAIL verdict plus a one-sentence explanation.

The aggregate metric is pass-rate broken down by category. Failures
surface the judge's reasoning so the user can spot patterns ("agent
drifted on put-side IVs", "model hallucinated on TSLA front-week", ...).

This complements the rule-based eval harness in `src/voli/eval/runner.py`:

  * Rule-based eval = synthetic data, exact-match metrics, free, fast,
    deterministic. Run on every PR.
  * LLM-as-judge eval = live Polygon data, rubric-graded, ~$1-2 per
    full run, has variance. Run before merging behavioural changes
    (new system prompt, new model, refactored tool descriptions).
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from voli.cli_render import THEMES, make_theme
from voli.llm import build_default_tools, llm_ask
from voli.llm.agent import collect
from voli.llm.analytics_tools import (
    _tool_compute_atm_iv_term_structure,
    _tool_compute_skew_slope,
    _tool_get_atm_greeks,
)
from voli.llm.provider import LLMProvider, make_provider

# ----------------------------------------------------------------------------
# Reference fetchers - the analytics tools called directly, no LLM mediation.
# ----------------------------------------------------------------------------


REFERENCE_FETCHERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "compute_atm_iv_term_structure": _tool_compute_atm_iv_term_structure,
    "compute_skew_slope": _tool_compute_skew_slope,
    "get_atm_greeks": _tool_get_atm_greeks,
}


# ----------------------------------------------------------------------------
# Dataset loading
# ----------------------------------------------------------------------------


def default_dataset_path() -> Path:
    return Path(__file__).resolve().parents[3] / "eval" / "llm_prompts.jsonl"


@dataclass(frozen=True)
class LLMEvalCase:
    id: str
    prompt: str
    category: str
    reference_tool: str
    reference_args: dict[str, Any]
    rubric_hint: str


def load_cases(path: Path | str) -> list[LLMEvalCase]:
    p = Path(path)
    out: list[LLMEvalCase] = []
    with p.open("r", encoding="utf-8") as f:
        for ln, line in enumerate(f, start=1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{p}:{ln}: invalid JSON: {exc}") from exc
            out.append(
                LLMEvalCase(
                    id=row["id"],
                    prompt=row["prompt"],
                    category=row["category"],
                    reference_tool=row["reference_tool"],
                    reference_args=row.get("reference_args", {}),
                    rubric_hint=row.get("rubric_hint", ""),
                )
            )
    return out


# ----------------------------------------------------------------------------
# Per-case evaluation
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class LLMEvalResult:
    case: LLMEvalCase
    reference_data: str  # raw JSON returned by the analytics tool
    sut_answer: str
    sut_tool_calls: int
    verdict: str  # 'PASS' | 'FAIL' | 'ERROR'
    reasoning: str
    elapsed_seconds: float


JUDGE_SYSTEM_PROMPT = """\
You are an evaluator for an options-data agent. You will receive:
  1. The user's prompt.
  2. The reference data fetched directly from Polygon (the ground truth).
  3. The agent's answer (which was generated using its own tool calls).
  4. A rubric_hint describing the tolerance for this specific case.

Decide whether the agent's answer is grounded in the reference data
within the rubric_hint tolerance.

Respond ONLY in this exact format, on two lines:

VERDICT: PASS
REASONING: <one short sentence>

or

VERDICT: FAIL
REASONING: <one short sentence>

Pass criteria:
  * Every numeric value in the agent's answer matches the reference data
    within the rubric_hint tolerance.
  * Direction (positive vs negative skew, IV up vs down) is correct.
  * The agent identifies the right ATM strike and expiries.

Fail criteria:
  * Numbers differ by more than the rubric_hint tolerance.
  * Wrong sign / direction.
  * Made-up data not present in the reference.
  * Refused to answer when reference data is available.

Minor wording variation is fine. Round numbers in either direction count
as a match if within tolerance.
"""


def _build_judge_user_message(case: LLMEvalCase, reference: str, sut_answer: str) -> str:
    return (
        f"PROMPT:\n{case.prompt}\n\n"
        f"REFERENCE DATA (JSON from Polygon):\n{reference}\n\n"
        f"SUT ANSWER:\n{sut_answer}\n\n"
        f"RUBRIC HINT:\n{case.rubric_hint}\n"
    )


_VERDICT_RE = re.compile(r"VERDICT:\s*(PASS|FAIL)", re.IGNORECASE)
_REASONING_RE = re.compile(r"REASONING:\s*(.+)", re.IGNORECASE | re.DOTALL)


def _parse_judge_response(text: str) -> tuple[str, str]:
    """Extract (verdict, reasoning) from the judge's free-form output.

    The judge is told to respond in a strict format but may add stray
    whitespace or markdown. We accept the first VERDICT/REASONING pair we
    find. Anything malformed becomes 'ERROR' so it shows up clearly.
    """

    v_match = _VERDICT_RE.search(text or "")
    if not v_match:
        return "ERROR", f"could not parse verdict from: {text[:200]!r}"
    verdict = v_match.group(1).upper()

    r_match = _REASONING_RE.search(text or "")
    reasoning = (r_match.group(1).strip() if r_match else "(no reasoning)").splitlines()
    return verdict, reasoning[0] if reasoning else "(no reasoning)"


def evaluate_case(
    case: LLMEvalCase,
    *,
    sut_provider: LLMProvider,
    judge_provider: LLMProvider,
    sut_tools=None,
) -> LLMEvalResult:
    """Run reference -> SUT -> judge for one case.

    Errors anywhere in the pipeline are captured into the verdict so a
    single broken case doesn't tank the whole run.
    """

    started = time.monotonic()

    # 1. Reference -- direct analytics call, no LLM.
    fetcher = REFERENCE_FETCHERS.get(case.reference_tool)
    if fetcher is None:
        return LLMEvalResult(
            case=case,
            reference_data="",
            sut_answer="",
            sut_tool_calls=0,
            verdict="ERROR",
            reasoning=f"unknown reference_tool {case.reference_tool!r}",
            elapsed_seconds=time.monotonic() - started,
        )

    try:
        reference_data = fetcher(case.reference_args)
    except Exception as exc:  # noqa: BLE001
        return LLMEvalResult(
            case=case,
            reference_data="",
            sut_answer="",
            sut_tool_calls=0,
            verdict="ERROR",
            reasoning=f"reference fetch failed: {type(exc).__name__}: {exc}",
            elapsed_seconds=time.monotonic() - started,
        )

    # 2. SUT -- the LLM agent answering the natural-language prompt.
    try:
        events = llm_ask(
            case.prompt,
            provider=sut_provider,
            tools=sut_tools or build_default_tools(),
        )
        sut_result = collect(events)
    except Exception as exc:  # noqa: BLE001
        return LLMEvalResult(
            case=case,
            reference_data=reference_data,
            sut_answer="",
            sut_tool_calls=0,
            verdict="ERROR",
            reasoning=f"SUT failed: {type(exc).__name__}: {exc}",
            elapsed_seconds=time.monotonic() - started,
        )

    # 3. Judge -- separate LLM call with strict-format rubric.
    try:
        judge_provider.start(
            system=JUDGE_SYSTEM_PROMPT,
            tools=[],  # judge has no tools; pure text-in / text-out
            user_message=_build_judge_user_message(case, reference_data, sut_result.answer),
            max_tokens=200,
            temperature=0.0,
        )
        # Drain the judge's single step.
        from voli.llm.types import StepComplete, TextDelta

        text_buf: list[str] = []
        for ev in judge_provider.step():
            if isinstance(ev, TextDelta):
                text_buf.append(ev.text)
            elif isinstance(ev, StepComplete):
                break
        judge_text = "".join(text_buf)
    except Exception as exc:  # noqa: BLE001
        return LLMEvalResult(
            case=case,
            reference_data=reference_data,
            sut_answer=sut_result.answer,
            sut_tool_calls=len(sut_result.tool_calls),
            verdict="ERROR",
            reasoning=f"judge failed: {type(exc).__name__}: {exc}",
            elapsed_seconds=time.monotonic() - started,
        )

    verdict, reasoning = _parse_judge_response(judge_text)
    return LLMEvalResult(
        case=case,
        reference_data=reference_data,
        sut_answer=sut_result.answer,
        sut_tool_calls=len(sut_result.tool_calls),
        verdict=verdict,
        reasoning=reasoning,
        elapsed_seconds=time.monotonic() - started,
    )


# ----------------------------------------------------------------------------
# Aggregation + report
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class LLMEvalReport:
    results: tuple[LLMEvalResult, ...] = ()
    by_category: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.verdict == "PASS")

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.verdict == "FAIL")

    @property
    def errored(self) -> int:
        return sum(1 for r in self.results if r.verdict == "ERROR")


def _group_by_category(results: list[LLMEvalResult]) -> dict[str, tuple[int, int]]:
    out: dict[str, list[int]] = {}
    for r in results:
        slot = out.setdefault(r.case.category, [0, 0])
        slot[1] += 1
        if r.verdict == "PASS":
            slot[0] += 1
    return {k: (v[0], v[1]) for k, v in out.items()}


def render_report(
    report: LLMEvalReport,
    *,
    color: bool | None = None,
    theme: str | None = None,
) -> str:
    t = make_theme(color, theme=theme)
    width = 80
    lines: list[str] = []
    lines.append(t.dim("=" * width))
    summary = f"VOLI LLM EVAL | {report.total} cases | {report.passed} pass | {report.failed} fail"
    if report.errored:
        summary += f" | {report.errored} error"
    lines.append(t.status_bar(summary))
    lines.append(t.dim("=" * width))

    lines.append(t.header("[ RESULTS ]"))
    for r in report.results:
        if r.verdict == "PASS":
            marker = t.good("PASS")
        elif r.verdict == "ERROR":
            marker = t.warn("ERROR")
        else:
            marker = t.warn("FAIL")
        prompt = r.case.prompt if len(r.case.prompt) <= 50 else r.case.prompt[:47] + "..."
        elapsed = f"{r.elapsed_seconds:5.1f}s"
        lines.append(
            f"{marker}  {t.label(r.case.id.ljust(8))}  "
            f"{t.value(r.case.category.ljust(16))}  "
            f"{t.dim(elapsed)}  "
            f"{t.dim(prompt)}"
        )
        if r.verdict != "PASS":
            lines.append(f"        {t.dim('->')} {t.value(r.reasoning)}")

    lines.append("")
    lines.append(t.header("[ BY CATEGORY ]"))
    for cat in sorted(report.by_category):
        passed, total = report.by_category[cat]
        ratio = f"{passed}/{total}"
        marker = t.good(ratio) if passed == total else t.warn(ratio)
        lines.append(f"{t.label(cat.ljust(20))}  {marker}")

    lines.append(t.dim("=" * width))
    return "\n".join(lines)


def render_report_json(report: LLMEvalReport) -> str:
    return json.dumps(
        {
            "total": report.total,
            "passed": report.passed,
            "failed": report.failed,
            "errored": report.errored,
            "by_category": {
                k: {"passed": v[0], "total": v[1]} for k, v in report.by_category.items()
            },
            "cases": [
                {
                    "id": r.case.id,
                    "category": r.case.category,
                    "prompt": r.case.prompt,
                    "verdict": r.verdict,
                    "reasoning": r.reasoning,
                    "tool_calls": r.sut_tool_calls,
                    "elapsed_seconds": round(r.elapsed_seconds, 2),
                    "sut_answer": r.sut_answer,
                    "reference_data": r.reference_data,
                }
                for r in report.results
            ],
        },
        indent=2,
        sort_keys=True,
        default=str,
    )


# ----------------------------------------------------------------------------
# Top-level entry points
# ----------------------------------------------------------------------------


def run_eval(
    *,
    dataset: Path | str | None = None,
    sut_provider: LLMProvider | None = None,
    judge_provider: LLMProvider | None = None,
    limit: int | None = None,
    on_case: Callable[[LLMEvalResult], None] | None = None,
) -> LLMEvalReport:
    """Run the full eval (or first `limit` cases). Returns the report.

    `on_case` is called after each case completes - useful for live
    progress output during a long run.
    """

    cases = load_cases(dataset or default_dataset_path())
    if limit is not None:
        cases = cases[:limit]
    sut = sut_provider or make_provider("anthropic")
    judge = judge_provider or make_provider("anthropic", model="claude-opus-4-7")

    results: list[LLMEvalResult] = []
    for case in cases:
        result = evaluate_case(case, sut_provider=sut, judge_provider=judge)
        results.append(result)
        if on_case is not None:
            on_case(result)

    return LLMEvalReport(
        results=tuple(results),
        by_category=_group_by_category(results),
    )


def main(argv: list[str] | None = None, *, out=None) -> int:
    """CLI-style entry point. Returns exit code (0 = all PASS, 1 otherwise)."""

    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="voli-llm-eval",
        description="Run the VOLI LLM-as-judge evaluation harness.",
    )
    parser.add_argument(
        "--dataset", default=None, help="Path to JSONL dataset (default eval/llm_prompts.jsonl)."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Run only the first N cases (for dry-runs / cost control).",
    )
    parser.add_argument("--sut-provider", default="anthropic", choices=["anthropic", "openai"])
    parser.add_argument("--sut-model", default=None, help="Override SUT model (else SDK default).")
    parser.add_argument("--judge-provider", default="anthropic", choices=["anthropic", "openai"])
    parser.add_argument(
        "--judge-model",
        default="claude-opus-4-7",
        help="Override judge model (default: claude-opus-4-7).",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit JSON instead of the themed report."
    )
    parser.add_argument("--theme", default=None, choices=sorted(THEMES.keys()), metavar="NAME")
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args(argv)

    out = out or sys.stdout
    color = False if args.no_color else None

    sut = make_provider(args.sut_provider, model=args.sut_model)
    judge = make_provider(args.judge_provider, model=args.judge_model)

    # Live per-case marker so a long run shows progress.
    t = make_theme(color, theme=args.theme)

    def _progress(r: LLMEvalResult) -> None:
        if args.json:
            return  # JSON mode stays quiet until the end
        marker = t.good("PASS") if r.verdict == "PASS" else t.warn(r.verdict)
        print(
            f"  {marker}  {t.label(r.case.id)}  {t.dim(f'{r.elapsed_seconds:.1f}s')}",
            file=out,
            flush=True,
        )

    if not args.json:
        print(t.dim(f"running {args.dataset or default_dataset_path()} ..."), file=out)

    report = run_eval(
        dataset=args.dataset,
        sut_provider=sut,
        judge_provider=judge,
        limit=args.limit,
        on_case=_progress,
    )

    if args.json:
        print(render_report_json(report), file=out)
    else:
        print(render_report(report, color=color, theme=args.theme), file=out)

    return 0 if (report.failed == 0 and report.errored == 0) else 1
