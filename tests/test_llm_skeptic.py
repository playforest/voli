"""Stage C: LLM-mode skeptic tests.

We don't need a live LLM - the skeptic operates on tool-result JSON
strings, which we hand-craft per test. The aim is to verify that the
checks fire on the same data shapes the analytics + raw tools actually
emit.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from oqe.agent.skeptic import STALE_SNAPSHOT_MAX_AGE_MINUTES
from oqe.llm.skeptic import review_llm_run
from oqe.llm.types import ToolResult


def _r(name: str, payload: dict) -> ToolResult:
    return ToolResult(id=f"id-{name}", name=name, content=json.dumps(payload))


# ---- happy path ------------------------------------------------------------


def test_clean_results_yield_no_concerns() -> None:
    fresh = datetime.now(UTC).isoformat()
    results = [
        _r(
            "get_underlying_snapshot",
            {
                "snapshot": {"ticker": "NVDA", "spot": 100.0, "ts": fresh, "source": "polygon"},
                "meta": {"warnings": []},
            },
        ),
        _r(
            "compute_atm_iv_term_structure",
            {
                "ticker": "NVDA",
                "spot": 100.0,
                "atm_strike": 100.0,
                "front_iv": 0.30,
                "next_iv": 0.35,
                "flags": [],
            },
        ),
    ]
    assert review_llm_run(results) == []


# ---- individual checks -----------------------------------------------------


def test_stale_snapshot_fires_on_old_underlying_ts() -> None:
    old = (datetime.now(UTC) - timedelta(minutes=STALE_SNAPSHOT_MAX_AGE_MINUTES + 5)).isoformat()
    results = [
        _r(
            "get_underlying_snapshot",
            {
                "snapshot": {"ticker": "NVDA", "spot": 100.0, "ts": old, "source": "polygon"},
            },
        ),
    ]
    codes = [c.code for c in review_llm_run(results)]
    assert "STALE_SNAPSHOT" in codes


def test_atm_gap_fires_on_analytics_result() -> None:
    """The analytics tool returns spot + atm_strike together; when the strike
    sits >5% from spot we flag it.
    """

    results = [
        _r(
            "compute_atm_iv_term_structure",
            {
                "ticker": "NVDA",
                "spot": 100.0,
                "atm_strike": 110.0,  # 10% gap
                "front_iv": 0.30,
                "next_iv": 0.35,
                "flags": [],
            },
        )
    ]
    codes = [c.code for c in review_llm_run(results)]
    assert "ATM_GAP" in codes


def test_atm_gap_fires_when_get_atm_greeks_nests_strike() -> None:
    """get_atm_greeks puts strike under `atm.strike`; check still fires."""

    results = [
        _r(
            "get_atm_greeks",
            {
                "ticker": "NVDA",
                "spot": 100.0,
                "atm": {
                    "strike": 110.0,
                    "iv": 0.30,
                    "delta": 0.5,
                    "gamma": 0.02,
                    "theta": -0.1,
                    "vega": 0.1,
                },
            },
        )
    ]
    codes = [c.code for c in review_llm_run(results)]
    assert "ATM_GAP" in codes


def test_tool_error_short_circuits_other_checks() -> None:
    """If a tool returned an error payload, we report TOOL_ERROR and skip
    the rest of the checks for that result.
    """

    results = [
        _r(
            "compute_atm_iv_term_structure",
            {
                "error": "no_contracts",
                "ticker": "ZZZZ",
            },
        )
    ]
    concerns = review_llm_run(results)
    assert len(concerns) == 1
    assert concerns[0].code == "TOOL_ERROR"
    assert concerns[0].severity == "critical"


def test_meta_warnings_promoted_to_concerns() -> None:
    fresh = datetime.now(UTC).isoformat()
    results = [
        _r(
            "get_underlying_snapshot",
            {
                "snapshot": {"ticker": "NVDA", "spot": 100.0, "ts": fresh, "source": "polygon"},
                "meta": {"warnings": ["STALE_DATA", "PARTIAL_DATA"]},
            },
        )
    ]
    codes = [c.code for c in review_llm_run(results)]
    assert "STALE_DATA" in codes
    assert "PARTIAL_DATA" in codes


def test_analytics_flags_promoted_to_concerns() -> None:
    """Analytics tools surface flags (FILTERED_WIDE_SPREAD, etc.). The
    skeptic forwards them as info-level concerns.
    """

    results = [
        _r(
            "compute_atm_iv_term_structure",
            {
                "ticker": "NVDA",
                "spot": 100.0,
                "atm_strike": 100.0,
                "front_iv": 0.30,
                "next_iv": 0.35,
                "flags": ["FILTERED_WIDE_SPREAD"],
            },
        )
    ]
    codes = [c.code for c in review_llm_run(results)]
    assert "FILTERED_WIDE_SPREAD" in codes


# ---- ordering --------------------------------------------------------------


def test_concerns_sorted_critical_first() -> None:
    fresh = datetime.now(UTC).isoformat()
    results = [
        _r(
            "compute_atm_iv_term_structure",
            {
                "ticker": "NVDA",
                "spot": 100.0,
                "atm_strike": 110.0,  # ATM_GAP warn
                "front_iv": 0.30,
                "next_iv": 0.35,
                "flags": [],
            },
        ),
        _r(
            "get_underlying_snapshot",
            {
                "snapshot": {"ticker": "NVDA", "spot": 100.0, "ts": fresh, "source": "polygon"},
                "meta": {"warnings": ["NO_RESULTS"]},  # critical
            },
        ),
    ]
    concerns = review_llm_run(results)
    assert concerns[0].severity == "critical"
    assert concerns[0].code == "NO_RESULTS"


def test_dedupes_repeated_concerns() -> None:
    """A flag forwarded from two analytics tools shouldn't show up twice."""

    results = [
        _r(
            "compute_atm_iv_term_structure",
            {
                "ticker": "NVDA",
                "spot": 100.0,
                "atm_strike": 100.0,
                "flags": ["FILTERED_WIDE_SPREAD"],
            },
        ),
        _r(
            "compute_skew_slope",
            {
                "ticker": "NVDA",
                "spot": 100.0,
                "flags": ["FILTERED_WIDE_SPREAD"],
            },
        ),
    ]
    concerns = review_llm_run(results)
    codes = [c.code for c in concerns]
    assert codes.count("FILTERED_WIDE_SPREAD") == 1


def test_unparseable_content_is_skipped_silently() -> None:
    """A tool result that isn't JSON shouldn't crash the reviewer."""

    results = [ToolResult(id="x", name="weird", content="not json at all")]
    assert review_llm_run(results) == []
