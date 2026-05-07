"""Skeptic sub-agent.

Runs after the writer and reviews the AnswerResponse against a quality
checklist. Doesn't override the answer - it produces concerns the
renderer surfaces in a `[ SKEPTIC ]` block so the user can decide.

Why a separate stage rather than folding into the writer?

  * The writer's `numbers_used` guardrail catches *invented* numbers.
    The skeptic catches *suspicious* numbers (stale snapshots, illiquid
    quotes, missing greeks). Different concern, different stage.
  * The skeptic's checks depend on the raw tool outputs that drove the
    metrics, not just the rendered facts dict.
  * Easy to extend: new checks are pure functions added to one place.

Concerns are returned as `SkepticConcern` records so callers can filter
by severity (info / warn / critical) before rendering.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from .state import AnswerResponse

Severity = Literal["info", "warn", "critical"]

# Tunables. Conservative defaults; ATM-spread + stale-snapshot are the most
# common real-world quality issues.
STALE_SNAPSHOT_MAX_AGE_MINUTES = 30
WIDE_SPREAD_RELATIVE_THRESHOLD = 0.20
LOW_CONTRACT_COUNT_THRESHOLD = 4
ATM_GAP_RELATIVE_THRESHOLD = 0.05


@dataclass(frozen=True)
class SkepticConcern:
    """One reviewer note. `code` is stable; `message` is human-readable."""

    code: str
    severity: Severity
    message: str

    def render(self) -> str:
        # Renderer-friendly compact form. Keep order stable so themes can
        # colour-code by severity.
        return f"{self.severity.upper():8}  {self.code:24}  {self.message}"


# --- individual checks ------------------------------------------------------


def _check_stale_snapshot(facts: dict[str, Any]) -> SkepticConcern | None:
    spot = facts.get("spot")
    if not isinstance(spot, dict):
        return None
    ts_raw = spot.get("ts")
    if ts_raw is None:
        return None
    try:
        # Accept ISO strings ('2026-05-05T12:34:56Z' or with offset).
        if isinstance(ts_raw, str):
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        elif isinstance(ts_raw, datetime):
            ts = ts_raw
        else:
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None

    age = datetime.now(UTC) - ts.astimezone(UTC)
    if age <= timedelta(minutes=STALE_SNAPSHOT_MAX_AGE_MINUTES):
        return None

    minutes = int(age.total_seconds() / 60)
    return SkepticConcern(
        code="STALE_SNAPSHOT",
        severity="warn",
        message=f"spot snapshot is {minutes}m old (threshold {STALE_SNAPSHOT_MAX_AGE_MINUTES}m).",
    )


def _check_atm_gap(facts: dict[str, Any]) -> SkepticConcern | None:
    """ATM strike too far from spot suggests a sparse strike grid."""

    spot = facts.get("spot")
    atm = facts.get("atm_strike")
    if not isinstance(spot, dict) or atm is None:
        return None
    spot_value = spot.get("value")
    if spot_value is None or spot_value == 0:
        return None
    gap = abs(float(atm) - float(spot_value)) / abs(float(spot_value))
    if gap <= ATM_GAP_RELATIVE_THRESHOLD:
        return None
    pct = gap * 100
    return SkepticConcern(
        code="ATM_GAP",
        severity="warn",
        message=f"chosen ATM strike is {pct:.1f}% away from spot - sparse strike grid?",
    )


def _check_low_contract_count(facts: dict[str, Any]) -> SkepticConcern | None:
    n = facts.get("contracts_count")
    if not isinstance(n, int) or n >= LOW_CONTRACT_COUNT_THRESHOLD:
        return None
    return SkepticConcern(
        code="LOW_CONTRACT_COUNT",
        severity="warn",
        message=f"only {n} contracts returned - chain may be illiquid or filter too narrow.",
    )


def _check_missing_greeks(facts: dict[str, Any]) -> SkepticConcern | None:
    """For greeks-category responses, flag any null field on the ATM contract."""

    atm = facts.get("atm_contract")
    if not isinstance(atm, dict):
        return None
    missing = [k for k in ("iv", "delta", "gamma", "theta", "vega") if atm.get(k) is None]
    if not missing:
        return None
    return SkepticConcern(
        code="MISSING_GREEKS",
        severity="warn",
        message=f"ATM contract missing greeks: {', '.join(missing)}.",
    )


def _check_wide_atm_spread(
    facts: dict[str, Any], tool_outputs: dict[str, Any]
) -> SkepticConcern | None:
    """Looks at the chain quotes (if available) for the ATM strike contract
    and warns if its bid-ask spread is wide enough that mid-price shouldn't
    be trusted.
    """

    atm = facts.get("atm_strike")
    quotes_obj = tool_outputs.get("quotes")
    contracts_obj = tool_outputs.get("contracts")
    if atm is None or quotes_obj is None or contracts_obj is None:
        return None

    quotes = list(getattr(quotes_obj, "quotes", []) or [])
    contracts = list(getattr(contracts_obj, "contracts", []) or [])
    if not quotes or not contracts:
        return None

    quotes_by_symbol = {q.option_symbol: q for q in quotes}
    for c in contracts:
        if float(getattr(c, "strike", 0)) != float(atm):
            continue
        q = quotes_by_symbol.get(getattr(c, "option_symbol", None))
        if q is None or q.bid is None or q.ask is None:
            continue
        bid, ask = float(q.bid), float(q.ask)
        if bid <= 0 or ask < bid:
            continue
        mid = (bid + ask) / 2
        if mid <= 0:
            continue
        rel = (ask - bid) / mid
        if rel <= WIDE_SPREAD_RELATIVE_THRESHOLD:
            continue
        pct = rel * 100
        return SkepticConcern(
            code="WIDE_ATM_SPREAD",
            severity="warn",
            message=(
                f"ATM contract bid/ask = {bid}/{ask} (spread {pct:.1f}% of mid) - "
                "mid price may not be tradeable."
            ),
        )
    return None


def _check_forwarded_warnings(response: AnswerResponse) -> Iterable[SkepticConcern]:
    """Promote every limitation the writer surfaced into a structured concern.

    These already appear in `[ LIMITATIONS ]`, but the skeptic block gives
    them a severity + code so they're scriptable.
    """

    severity_by_code: dict[str, Severity] = {
        "STALE_DATA": "warn",
        "PARTIAL_DATA": "warn",
        "NO_RESULTS": "critical",
        "VENDOR_LIMIT": "info",
        "MARKET_CLOSED": "info",
    }
    for code in response.limitations or ():
        sev = severity_by_code.get(code, "info")
        yield SkepticConcern(
            code=code,
            severity=sev,
            message=f"tool layer flagged {code}.",
        )


# --- public API -------------------------------------------------------------


def review(
    response: AnswerResponse, *, tool_outputs: dict[str, Any] | None = None
) -> list[SkepticConcern]:
    """Run every check and return ordered concerns (criticals first)."""

    out: list[SkepticConcern] = []
    if not response.supported:
        # Refusal / missing-ticker have nothing to review.
        return out

    facts = response.facts or {}
    tool_outputs = tool_outputs or {}

    for check in (
        _check_stale_snapshot,
        _check_atm_gap,
        _check_low_contract_count,
        _check_missing_greeks,
    ):
        concern = check(facts)
        if concern is not None:
            out.append(concern)

    spread_concern = _check_wide_atm_spread(facts, tool_outputs)
    if spread_concern is not None:
        out.append(spread_concern)

    out.extend(_check_forwarded_warnings(response))

    # Stable order: critical -> warn -> info, then by code.
    rank = {"critical": 0, "warn": 1, "info": 2}
    out.sort(key=lambda c: (rank[c.severity], c.code))
    return out
