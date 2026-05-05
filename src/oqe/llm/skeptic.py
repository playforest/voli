"""Skeptic for LLM-mode answers.

The rule-based skeptic in `oqe.agent.skeptic` keys off `AnswerResponse.facts`.
LLM mode doesn't produce that — it produces a stream of tool results (JSON
strings the LLM saw). This module bridges the two: we walk the LLM's tool
results, extract the same datapoints the rule-based skeptic checks, and
reuse the existing `SkepticConcern` shape so the renderer can stay generic.

What we look for:
  * Stale snapshot      - any get_underlying_snapshot result with an old ts.
  * ATM-strike vs spot  - any analytics result whose atm_strike sits >5% from spot.
  * No data             - tool results whose JSON contains "error".
  * Forwarded warnings  - meta.warnings from the polygon tool wrappers.

The checks are intentionally a subset of the rule-based version - LLM mode
doesn't emit the same Facts dict, so a few checks (LOW_CONTRACT_COUNT,
WIDE_ATM_SPREAD on the writer's chosen ATM) don't translate cleanly. We
keep the codes consistent so downstream consumers can treat both alike.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from oqe.agent.skeptic import (
    ATM_GAP_RELATIVE_THRESHOLD,
    STALE_SNAPSHOT_MAX_AGE_MINUTES,
    SkepticConcern,
)

from .types import ToolResult


def _parse_json(content: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _check_stale_ts(payload: dict[str, Any]) -> SkepticConcern | None:
    """Snapshot tools include `snapshot.ts`; analytics tools include
    `spot` (scalar) but no timestamp - so this only fires for the raw
    snapshot tool.
    """

    snap = payload.get("snapshot")
    if not isinstance(snap, dict):
        return None
    ts_raw = snap.get("ts")
    if not isinstance(ts_raw, str):
        return None
    try:
        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    age = datetime.now(UTC) - ts.astimezone(UTC)
    if age <= timedelta(minutes=STALE_SNAPSHOT_MAX_AGE_MINUTES):
        return None
    minutes = int(age.total_seconds() / 60)
    return SkepticConcern(
        code="STALE_SNAPSHOT",
        severity="warn",
        message=f"spot snapshot is {minutes}m old (threshold {STALE_SNAPSHOT_MAX_AGE_MINUTES}m).",
    )


def _check_atm_gap(payload: dict[str, Any]) -> SkepticConcern | None:
    """Analytics tools return both `spot` (scalar) and `atm_strike`."""

    spot = payload.get("spot")
    atm = payload.get("atm_strike")
    # `get_atm_greeks` nests the strike under `atm`.
    if atm is None:
        atm_block = payload.get("atm")
        if isinstance(atm_block, dict):
            atm = atm_block.get("strike")
    if not isinstance(spot, int | float) or not isinstance(atm, int | float):
        return None
    if spot == 0:
        return None
    gap = abs(float(atm) - float(spot)) / abs(float(spot))
    if gap <= ATM_GAP_RELATIVE_THRESHOLD:
        return None
    pct = gap * 100
    return SkepticConcern(
        code="ATM_GAP",
        severity="warn",
        message=f"chosen ATM strike is {pct:.1f}% away from spot - sparse strike grid?",
    )


def _check_tool_error(name: str, payload: dict[str, Any]) -> SkepticConcern | None:
    err = payload.get("error")
    if not err:
        return None
    return SkepticConcern(
        code="TOOL_ERROR",
        severity="critical",
        message=f"tool {name!r} returned error: {err}.",
    )


def _check_warnings(payload: dict[str, Any]) -> list[SkepticConcern]:
    """Polygon tool outputs include `meta.warnings`; analytics tools include
    `flags`. Promote both to structured concerns.
    """

    severity_by_code: dict[str, str] = {
        "STALE_DATA": "warn",
        "PARTIAL_DATA": "warn",
        "NO_RESULTS": "critical",
        "VENDOR_LIMIT": "info",
        "MARKET_CLOSED": "info",
    }
    out: list[SkepticConcern] = []
    seen: set[str] = set()

    meta = payload.get("meta")
    if isinstance(meta, dict):
        for code in meta.get("warnings") or ():
            if code in seen:
                continue
            seen.add(code)
            out.append(
                SkepticConcern(
                    code=code,
                    severity=severity_by_code.get(code, "info"),
                    message=f"tool layer flagged {code}.",
                )
            )

    for code in payload.get("flags") or ():
        if code in seen:
            continue
        seen.add(code)
        out.append(
            SkepticConcern(
                code=code,
                severity="info",
                message=f"analytics flagged {code}.",
            )
        )
    return out


def review_llm_run(tool_results: list[ToolResult]) -> list[SkepticConcern]:
    """Run all checks across every tool result, return ordered concerns.

    Order: critical -> warn -> info, then alphabetical by code, deduped.
    """

    concerns: list[SkepticConcern] = []
    for r in tool_results:
        payload = _parse_json(r.content)
        if payload is None:
            continue

        err = _check_tool_error(r.name, payload)
        if err is not None:
            concerns.append(err)
            # Don't run other checks if the tool itself errored.
            continue

        for check in (_check_stale_ts, _check_atm_gap):
            c = check(payload)
            if c is not None:
                concerns.append(c)

        concerns.extend(_check_warnings(payload))

    # Dedupe by (code, message), preserving order.
    seen: set[tuple[str, str]] = set()
    deduped: list[SkepticConcern] = []
    for c in concerns:
        key = (c.code, c.message)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)

    rank = {"critical": 0, "warn": 1, "info": 2}
    deduped.sort(key=lambda c: (rank[c.severity], c.code))
    return deduped
