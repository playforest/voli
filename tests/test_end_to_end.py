"""End-to-end pytest harness backed by the same dataset as `eval/run_eval.py`.

Each row in `eval/prompts.jsonl` becomes a parametrised test case so a single
broken behaviour shows up as one named failure rather than a blob.

Why duplicate the eval runner under pytest?
  * `eval/run_eval.py` is the human-facing tool: themed report, exit code.
  * `pytest` is the regression gate: per-case failure messages live alongside
    every other test, CI surfaces them, IDEs jump straight to the failed case.
Both call the same `evaluate_case`, so they can never disagree.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from oqe.eval.runner import default_dataset_path, evaluate_case, load_cases

DATASET = default_dataset_path()


def _ids(cases):
    return [c["id"] for c in cases]


CASES = load_cases(DATASET)


def test_dataset_is_loadable_and_non_empty():
    assert CASES, f"empty dataset: {DATASET}"
    # Sanity check: every case has at minimum an id and a prompt.
    for case in CASES:
        assert "id" in case and "prompt" in case, case


@pytest.mark.parametrize("case", CASES, ids=_ids(CASES))
def test_case(case: dict) -> None:
    """Run a single dataset row and assert every declared check passed.

    `evaluate_case` collects per-check pass/fail; we surface them via
    `pytest.fail` with the failing check names + details so the test output
    points straight at what's wrong.
    """

    result = evaluate_case(case)
    if not result.passed:
        details = "\n".join(f"  - {f.name}: {f.detail or '(no detail)'}" for f in result.failures)
        pytest.fail(f"{case['id']} failed:\n{details}")


def test_dataset_path_lives_under_repo_root() -> None:
    """Guard that future refactors don't break the path the eval shell uses."""

    repo_root = Path(__file__).resolve().parents[1]
    assert repo_root / "eval" / "prompts.jsonl" == DATASET
