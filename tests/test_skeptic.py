"""Skeptic sub-agent tests.

We feed the reviewer hand-built `AnswerResponse` objects so we can poke
each check in isolation. The end-to-end path (skeptic=True via the CLI)
is exercised in test_cli.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from oqe.agent.skeptic import (
    LOW_CONTRACT_COUNT_THRESHOLD,
    STALE_SNAPSHOT_MAX_AGE_MINUTES,
    SkepticConcern,
    review,
)
from oqe.agent.state import AnswerResponse


def _resp(**facts) -> AnswerResponse:
    return AnswerResponse(
        supported=True,
        category="term_structure",
        summary="x",
        table={"type": "term_structure", "rows": []},
        facts=facts,
        numbers_used=[],
        limitations=[],
        suggested_rewrites=[],
    )


# ---- individual checks ------------------------------------------------------


def test_no_concerns_for_clean_response() -> None:
    fresh = datetime.now(UTC).replace(microsecond=0).isoformat()
    resp = _resp(
        ticker="NVDA",
        spot={"value": 100.0, "ts": fresh, "source": "polygon"},
        atm_strike=100.0,
        front_iv=0.30,
        next_iv=0.35,
    )
    assert review(resp) == []


def test_stale_snapshot_warning() -> None:
    old = (datetime.now(UTC) - timedelta(minutes=STALE_SNAPSHOT_MAX_AGE_MINUTES + 5)).isoformat()
    resp = _resp(
        ticker="NVDA",
        spot={"value": 100.0, "ts": old, "source": "polygon"},
        atm_strike=100.0,
    )
    concerns = [c for c in review(resp) if c.code == "STALE_SNAPSHOT"]
    assert len(concerns) == 1
    assert concerns[0].severity == "warn"


def test_atm_gap_when_strike_far_from_spot() -> None:
    fresh = datetime.now(UTC).isoformat()
    resp = _resp(
        ticker="NVDA",
        spot={"value": 100.0, "ts": fresh, "source": "polygon"},
        atm_strike=110.0,  # 10% away from spot
    )
    concerns = [c for c in review(resp) if c.code == "ATM_GAP"]
    assert len(concerns) == 1


def test_low_contract_count() -> None:
    fresh = datetime.now(UTC).isoformat()
    resp = AnswerResponse(
        supported=True,
        category="chain",
        summary="x",
        table={"type": "chain_slice", "rows": []},
        facts={
            "ticker": "NVDA",
            "spot": {"value": 100.0, "ts": fresh, "source": "polygon"},
            "contracts_count": LOW_CONTRACT_COUNT_THRESHOLD - 1,
        },
        numbers_used=[],
        limitations=[],
        suggested_rewrites=[],
    )
    concerns = [c for c in review(resp) if c.code == "LOW_CONTRACT_COUNT"]
    assert len(concerns) == 1


def test_missing_greeks() -> None:
    fresh = datetime.now(UTC).isoformat()
    resp = AnswerResponse(
        supported=True,
        category="greeks",
        summary="x",
        table={"type": "greeks", "rows": []},
        facts={
            "ticker": "NVDA",
            "spot": {"value": 100.0, "ts": fresh, "source": "polygon"},
            "atm_contract": {
                "option_symbol": "x",
                "iv": 0.3,
                "delta": None,
                "gamma": None,
                "theta": -0.1,
                "vega": 0.1,
                "strike": 100,
                "expiry": "2026-05-09",
            },
        },
        numbers_used=[],
        limitations=[],
        suggested_rewrites=[],
    )
    concerns = [c for c in review(resp) if c.code == "MISSING_GREEKS"]
    assert len(concerns) == 1
    assert "delta" in concerns[0].message
    assert "gamma" in concerns[0].message


def test_forwarded_warnings_become_concerns() -> None:
    fresh = datetime.now(UTC).isoformat()
    resp = AnswerResponse(
        supported=True,
        category="term_structure",
        summary="x",
        table={"type": "term_structure", "rows": []},
        facts={
            "ticker": "NVDA",
            "spot": {"value": 100.0, "ts": fresh, "source": "polygon"},
            "atm_strike": 100.0,
        },
        numbers_used=[],
        limitations=["STALE_DATA", "PARTIAL_DATA"],
        suggested_rewrites=[],
    )
    concerns = review(resp)
    codes = [c.code for c in concerns]
    assert "STALE_DATA" in codes
    assert "PARTIAL_DATA" in codes


def test_review_skips_refused_responses() -> None:
    refused = AnswerResponse(
        supported=False,
        category="not_supported",
        summary="x",
        table={"type": "none", "rows": []},
        facts={"reason": "execution"},
        numbers_used=[],
    )
    assert review(refused) == []


def test_concerns_sorted_critical_first() -> None:
    """When a critical (NO_RESULTS) and warnings coexist, critical wins ordering."""

    fresh = datetime.now(UTC).isoformat()
    resp = AnswerResponse(
        supported=True,
        category="term_structure",
        summary="x",
        table={"type": "term_structure", "rows": []},
        facts={
            "ticker": "NVDA",
            "spot": {"value": 100.0, "ts": fresh, "source": "polygon"},
            "atm_strike": 110.0,  # ATM_GAP warn
        },
        numbers_used=[],
        limitations=["NO_RESULTS"],  # critical
        suggested_rewrites=[],
    )
    concerns = review(resp)
    assert concerns[0].severity == "critical"
    assert concerns[0].code == "NO_RESULTS"


def test_skeptic_concern_render_is_stable() -> None:
    c = SkepticConcern(code="X_Y_Z", severity="warn", message="hello world")
    rendered = c.render()
    assert "WARN" in rendered
    assert "X_Y_Z" in rendered
    assert "hello world" in rendered
