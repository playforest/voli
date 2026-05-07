"""Writer guardrail tests.

The writer must reject any summary that contains numeric tokens not present
in `numbers_used`. We test the `_finalize` helper directly because it is the
choke point that all per-category renderers go through.
"""

from __future__ import annotations

import pytest

from voli.agent.writer import GuardrailViolation, _allowed_numbers_in, _finalize


def test_finalize_passes_when_summary_only_uses_recorded_numbers() -> None:
    resp = _finalize(
        supported=True,
        category="term_structure",
        summary="front IV 0.42 vs next IV 0.45 (diff 0.03).",
        table={"type": "term_structure", "rows": []},
        facts={},
        numbers_used=[0.42, 0.45, 0.03],
    )
    assert resp.summary.startswith("front IV")


def test_finalize_rejects_invented_number() -> None:
    with pytest.raises(GuardrailViolation):
        _finalize(
            supported=True,
            category="term_structure",
            summary="front IV 0.42 vs next IV 0.99 (diff 0.03).",
            table={"type": "term_structure", "rows": []},
            facts={},
            numbers_used=[0.42, 0.45, 0.03],
        )


def test_iso_dates_are_not_treated_as_numeric_claims() -> None:
    # 2026-01-17 contains 2026, 01, 17 which are NOT in numbers_used. The
    # guardrail should ignore them because the date pattern is stripped first.
    resp = _finalize(
        supported=True,
        category="term_structure",
        summary="front expiry 2026-01-17 IV 0.42.",
        table={"type": "term_structure", "rows": []},
        facts={},
        numbers_used=[0.42],
    )
    assert "2026-01-17" in resp.summary


def test_option_symbols_are_not_treated_as_numeric_claims() -> None:
    resp = _finalize(
        supported=True,
        category="greeks",
        summary="ATM contract O:NVDA260117C00100000 iv=0.42.",
        table={"type": "greeks", "rows": []},
        facts={},
        numbers_used=[0.42],
    )
    assert "O:NVDA260117C00100000" in resp.summary


def test_allowed_numbers_in_returns_offending_tokens() -> None:
    bad = _allowed_numbers_in("front IV 0.42, oops 7.7", [0.42])
    assert bad == ["7.7"]
