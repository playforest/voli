"""Evaluation runner.

Loads a JSONL dataset of test cases (default `eval/prompts.jsonl`), runs each
prompt through `voli.agent.answer_question` against the synthetic registry, and
scores per-case checks. Produces a themed report that breaks failures down by
category, and exits non-zero when any case fails.

Each JSONL row has the shape:

    {
      "id":                       "tc_001",
      "prompt":                   "NVDA ATM IV this week vs next week",
      "ticker_default":           null,            // or "NVDA"
      "expected_supported":       true,
      "expected_category":        "term_structure",
      "expected_ticker":          "NVDA",
      "expected_tools":           [...]            // ordered tool sequence
      "expected_compute":         "term_structure",
      "expected_table_type":      "term_structure",
      "must_contain_in_summary":  [...],
      "must_have_facts_keys":     [...],
      "expected_metrics":         {"front_iv": 0.30, ...},
      "metrics_tolerance":        1e-6
    }

Any field can be omitted; the corresponding check is skipped.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from voli.agent import answer_question
from voli.agent.executor import ToolRegistry
from voli.cli_render import THEMES, make_theme

from .synth_market import make_registry

# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------


def default_dataset_path() -> Path:
    # eval/prompts.jsonl at the repo root.
    return Path(__file__).resolve().parents[3] / "eval" / "prompts.jsonl"


def load_cases(path: Path | str) -> list[dict[str, Any]]:
    p = Path(path)
    cases: list[dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as f:
        for ln, line in enumerate(f, start=1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                cases.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{p}:{ln}: invalid JSON: {exc}") from exc
    return cases


# ---------------------------------------------------------------------------
# Per-case execution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class CaseResult:
    id: str
    prompt: str
    category: str
    checks: tuple[CheckResult, ...]

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failures(self) -> tuple[CheckResult, ...]:
        return tuple(c for c in self.checks if not c.passed)


def _wrap_registry_with_call_log(reg: ToolRegistry, log: list[str]) -> ToolRegistry:
    """Wrap each tool so we can record the order in which they were called.

    The plan-shape check (`expected_tools`) needs the actual call sequence,
    not just the planner's intent.
    """

    def _wrap(name, fn):
        def _inner(inputs):
            log.append(name)
            return fn(inputs)

        return _inner

    return ToolRegistry(tools={n: _wrap(n, f) for n, f in reg.tools.items()})


def _check(name: str, ok: bool, detail: str = "") -> CheckResult:
    return CheckResult(name=name, passed=ok, detail=detail)


def _check_metric(metric: str, expected: float, actual: Any, tol: float) -> CheckResult:
    if actual is None:
        return _check(f"metric:{metric}", False, f"missing (expected {expected})")
    try:
        diff = abs(float(actual) - float(expected))
    except (TypeError, ValueError):
        return _check(f"metric:{metric}", False, f"non-numeric value: {actual!r}")
    if diff > tol:
        return _check(
            f"metric:{metric}",
            False,
            f"actual={actual} expected={expected} diff={diff:.2e} tol={tol:.2e}",
        )
    return _check(f"metric:{metric}", True)


def evaluate_case(case: dict[str, Any], *, registry: ToolRegistry | None = None) -> CaseResult:
    """Run one case through the agent and score every check declared on it."""

    reg = registry or make_registry()
    call_log: list[str] = []
    wrapped = _wrap_registry_with_call_log(reg, call_log)

    checks: list[CheckResult] = []
    try:
        resp = answer_question(
            case["prompt"],
            ticker_default=case.get("ticker_default"),
            registry=wrapped,
        )
    except Exception as exc:  # noqa: BLE001 - we surface the exception as a failure
        checks.append(_check("ran_without_exception", False, f"{type(exc).__name__}: {exc}"))
        return CaseResult(
            id=case["id"],
            prompt=case["prompt"],
            category=case.get("expected_category", "unknown"),
            checks=tuple(checks),
        )
    checks.append(_check("ran_without_exception", True))

    # supported flag --------------------------------------------------------
    if "expected_supported" in case:
        checks.append(
            _check(
                "supported",
                resp.supported == case["expected_supported"],
                f"actual={resp.supported} expected={case['expected_supported']}",
            )
        )

    # category --------------------------------------------------------------
    if "expected_category" in case:
        checks.append(
            _check(
                "category",
                resp.category == case["expected_category"],
                f"actual={resp.category!r} expected={case['expected_category']!r}",
            )
        )

    # ticker ---------------------------------------------------------------
    if "expected_ticker" in case:
        actual_ticker = resp.facts.get("ticker") if isinstance(resp.facts, dict) else None
        expected_ticker = case["expected_ticker"]
        checks.append(
            _check(
                "ticker",
                actual_ticker == expected_ticker,
                f"actual={actual_ticker!r} expected={expected_ticker!r}",
            )
        )

    # tool sequence --------------------------------------------------------
    if "expected_tools" in case:
        expected_tools = list(case["expected_tools"])
        checks.append(
            _check(
                "tool_sequence",
                call_log == expected_tools,
                f"actual={call_log} expected={expected_tools}",
            )
        )

    # table type -----------------------------------------------------------
    if "expected_table_type" in case:
        actual_type = (resp.table or {}).get("type")
        checks.append(
            _check(
                "table_type",
                actual_type == case["expected_table_type"],
                f"actual={actual_type!r} expected={case['expected_table_type']!r}",
            )
        )

    # facts keys -----------------------------------------------------------
    for key in case.get("must_have_facts_keys", []):
        present = isinstance(resp.facts, dict) and key in resp.facts
        checks.append(_check(f"facts.{key}", present, "missing" if not present else ""))

    # summary substrings ---------------------------------------------------
    for needle in case.get("must_contain_in_summary", []):
        ok = needle in (resp.summary or "")
        checks.append(_check(f"summary~{needle!r}", ok, "" if ok else "not found"))

    # numeric metrics ------------------------------------------------------
    metrics = case.get("expected_metrics", {})
    tol = float(case.get("metrics_tolerance", 1e-6))
    for metric, expected in metrics.items():
        actual = resp.facts.get(metric) if isinstance(resp.facts, dict) else None
        checks.append(_check_metric(metric, float(expected), actual, tol))

    return CaseResult(
        id=case["id"],
        prompt=case["prompt"],
        category=case.get("expected_category", resp.category),
        checks=tuple(checks),
    )


# ---------------------------------------------------------------------------
# Aggregation + report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvalReport:
    cases: tuple[CaseResult, ...] = ()
    by_category: dict[str, tuple[int, int]] = field(default_factory=dict)  # name -> (passed, total)

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.cases if c.passed)

    @property
    def failed(self) -> int:
        return self.total - self.passed


def _build_by_category(cases: Iterable[CaseResult]) -> dict[str, tuple[int, int]]:
    out: dict[str, list[int]] = {}
    for c in cases:
        slot = out.setdefault(c.category, [0, 0])
        slot[1] += 1
        if c.passed:
            slot[0] += 1
    return {k: (v[0], v[1]) for k, v in out.items()}


def render_report(
    report: EvalReport, *, color: bool | None = None, theme: str | None = None
) -> str:
    """Bloomberg-themed report (uses cli_render's theme)."""

    t = make_theme(color, theme=theme)
    width = 80
    lines: list[str] = []
    lines.append(t.dim("=" * width))
    lines.append(
        t.status_bar(
            f"Voli EVAL | {report.total} cases | {report.passed} passed | {report.failed} failed"
        )
    )
    lines.append(t.dim("=" * width))

    lines.append(t.header("[ RESULTS ]"))
    for c in report.cases:
        marker = t.good("PASS") if c.passed else t.warn("FAIL")
        prompt = c.prompt if len(c.prompt) <= 50 else c.prompt[:47] + "..."
        lines.append(
            f"{marker}  {t.label(c.id.ljust(8))}  {t.value(c.category.ljust(16))}  {t.dim(prompt)}"
        )
        for f in c.failures:
            lines.append(
                f"        {t.dim('->')} {t.warn(f.name)}: {t.value(f.detail or '(no detail)')}"
            )

    lines.append("")
    lines.append(t.header("[ BY CATEGORY ]"))
    for cat in sorted(report.by_category):
        passed, total = report.by_category[cat]
        ratio = f"{passed}/{total}"
        marker = t.good(ratio) if passed == total else t.warn(ratio)
        lines.append(f"{t.label(cat.ljust(20))}  {marker}")

    lines.append(t.dim("=" * width))
    return "\n".join(lines)


def render_report_json(report: EvalReport) -> str:
    return json.dumps(
        {
            "total": report.total,
            "passed": report.passed,
            "failed": report.failed,
            "by_category": {
                k: {"passed": v[0], "total": v[1]} for k, v in report.by_category.items()
            },
            "cases": [
                {
                    "id": c.id,
                    "prompt": c.prompt,
                    "category": c.category,
                    "passed": c.passed,
                    "failures": [{"name": f.name, "detail": f.detail} for f in c.failures],
                }
                for c in report.cases
            ],
        },
        indent=2,
        sort_keys=True,
    )


# ---------------------------------------------------------------------------
# Top-level entry points
# ---------------------------------------------------------------------------


def run_eval(
    dataset: Path | str | None = None,
    *,
    registry: ToolRegistry | None = None,
) -> EvalReport:
    """Run the full eval and return the EvalReport."""

    cases_data = load_cases(dataset or default_dataset_path())
    results = tuple(evaluate_case(c, registry=registry) for c in cases_data)
    return EvalReport(cases=results, by_category=_build_by_category(results))


def main(
    argv: list[str] | None = None,
    *,
    out=None,
    registry: ToolRegistry | None = None,
) -> int:
    """CLI-style entry point. Returns an exit code (0 = all passed)."""

    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="voli-eval", description="Run the Voli evaluation harness."
    )
    parser.add_argument(
        "--dataset", default=None, help="Path to JSONL dataset (default: eval/prompts.jsonl)."
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit JSON instead of the themed report."
    )
    parser.add_argument("--theme", default=None, choices=sorted(THEMES.keys()), metavar="NAME")
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args(argv)

    out = out or sys.stdout
    report = run_eval(args.dataset, registry=registry)
    if args.json:
        print(render_report_json(report), file=out)
    else:
        color = False if args.no_color else None
        print(render_report(report, color=color, theme=args.theme), file=out)
    return 0 if report.failed == 0 else 1
