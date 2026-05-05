"""Writer: turn the executed AgentState into a grounded AnswerResponse.

Two guardrails enforce v1 contract guarantees from docs/v1_contract.md:

1. **No invented numbers**: every numeric token that appears in `summary`
   must correspond to a value in `numbers_used` (within tolerance). Dates
   and option symbols are stripped before checking.
2. **Facts section is mandatory**: `facts` always contains the raw data the
   summary refers to, plus timestamps and sources where available.

If a guardrail fails, the writer raises `GuardrailViolation` rather than
emitting a misleading answer; tests assert this never happens for v1 prompts.
"""

from __future__ import annotations

import math
import re
from typing import Any

from .state import AgentState, AnswerResponse


class GuardrailViolation(RuntimeError):
    """Raised when the writer would emit an answer that violates a v1 guarantee."""


_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_OPTION_SYMBOL_RE = re.compile(r"O:[A-Z]+\d+[CP]\d+")
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
_TOLERANCE = 1e-4


def _allowed_numbers_in(text: str, allowed: list[float]) -> list[str]:
    """Return numeric tokens in `text` that don't match any value in `allowed`.

    Tokens inside ISO dates or option symbols are skipped first because those
    aren't numeric claims the writer is asserting.
    """

    scrubbed = _OPTION_SYMBOL_RE.sub("", _ISO_DATE_RE.sub("", text))
    out: list[str] = []
    for tok in _NUMBER_RE.findall(scrubbed):
        try:
            v = float(tok)
        except ValueError:
            continue
        if not any(_close(v, a) for a in allowed):
            out.append(tok)
    return out


def _close(a: float, b: float) -> bool:
    if math.isnan(a) or math.isnan(b):
        return False
    return abs(a - b) <= max(_TOLERANCE, _TOLERANCE * abs(b))


# Per-category renderers ------------------------------------------------------


def _render_chain(state: AgentState) -> AnswerResponse:
    intent = state.intent
    assert intent is not None
    spot_obj = state.tool_outputs.get("spot")
    contracts_obj = state.tool_outputs.get("contracts")
    quotes_obj = state.tool_outputs.get("quotes")

    spot_value = spot_obj.snapshot.spot if spot_obj else None
    contracts = list(getattr(contracts_obj, "contracts", []) or [])
    quotes = list(getattr(quotes_obj, "quotes", []) or [])
    quotes_by_symbol = {q.option_symbol: q for q in quotes}

    rows: list[dict[str, Any]] = []
    for c in contracts:
        q = quotes_by_symbol.get(c.option_symbol)
        rows.append(
            {
                "option_symbol": c.option_symbol,
                "expiry": str(c.expiry),
                "strike": float(c.strike),
                "right": c.right,
                "bid": getattr(q, "bid", None) if q else None,
                "ask": getattr(q, "ask", None) if q else None,
                "mid": getattr(q, "mid", None) if q else None,
                "last": getattr(q, "last", None) if q else None,
                "ts": str(getattr(q, "ts", "")) if q else None,
            }
        )

    numbers_used: list[float] = []
    if spot_value is not None:
        numbers_used.append(float(spot_value))
    numbers_used.append(float(len(rows)))

    summary_parts = []
    if intent.ticker:
        summary_parts.append(f"{intent.ticker} chain slice:")
    summary_parts.append(f"{len(rows)} contracts returned.")
    if spot_value is not None:
        summary_parts.append(f"Spot {float(spot_value)}.")
    summary = " ".join(summary_parts)

    facts: dict[str, Any] = {
        "ticker": intent.ticker,
        "spot": _spot_fact(spot_obj),
        "contracts_count": len(rows),
        "expiries_used": sorted({r["expiry"] for r in rows}),
        "right_filter": intent.right,
    }

    return _finalize(
        supported=True,
        category="chain",
        summary=summary,
        table={"type": "chain_slice", "rows": rows},
        facts=facts,
        numbers_used=numbers_used,
        limitations=_limitations_from(spot_obj, quotes_obj),
    )


def _render_term_structure(state: AgentState) -> AnswerResponse:
    intent = state.intent
    assert intent is not None
    spot_obj = state.tool_outputs.get("spot")
    bundle = state.metrics.get("bundle")

    ts = getattr(bundle, "term_structure", None)
    spot_value = spot_obj.snapshot.spot if spot_obj else None

    rows: list[dict[str, Any]] = []
    front_iv = next_iv = atm_strike = None
    if ts is not None:
        atm_strike = ts.atm_strike
        front_iv = ts.front_iv
        next_iv = ts.next_iv
        if ts.front_expiry is not None:
            rows.append(
                {
                    "expiry": str(ts.front_expiry),
                    "atm_strike": atm_strike,
                    "atm_iv": front_iv,
                }
            )
        if ts.next_expiry is not None:
            rows.append(
                {
                    "expiry": str(ts.next_expiry),
                    "atm_strike": atm_strike,
                    "atm_iv": next_iv,
                }
            )

    numbers_used: list[float] = []
    if spot_value is not None:
        numbers_used.append(float(spot_value))
    if atm_strike is not None:
        numbers_used.append(float(atm_strike))
    if front_iv is not None:
        numbers_used.append(float(front_iv))
    if next_iv is not None:
        numbers_used.append(float(next_iv))
    diff = None
    if front_iv is not None and next_iv is not None:
        # Round to suppress float-precision noise (0.35 - 0.30 = 0.04999...).
        # The guardrail tolerance (1e-4) absorbs the rounding.
        diff = round(float(next_iv - front_iv), 4)
        numbers_used.append(diff)

    parts = []
    if intent.ticker:
        parts.append(f"{intent.ticker} ATM IV term structure:")
    if front_iv is not None and next_iv is not None and atm_strike is not None:
        parts.append(
            f"front IV {float(front_iv)} vs next IV {float(next_iv)} "
            f"at strike {float(atm_strike)} (diff {diff})."
        )
    elif ts is not None and ts.flags:
        parts.append("term structure unavailable (see Facts.flags).")
    summary = " ".join(parts)

    facts: dict[str, Any] = {
        "ticker": intent.ticker,
        "spot": _spot_fact(spot_obj),
        "right_used": state.metrics.get("right_used"),
        "atm_strike": atm_strike,
        "front_expiry": str(ts.front_expiry) if ts and ts.front_expiry else None,
        "next_expiry": str(ts.next_expiry) if ts and ts.next_expiry else None,
        "front_iv": front_iv,
        "next_iv": next_iv,
        "flags": list(getattr(ts, "flags", ()) or ()),
    }

    return _finalize(
        supported=True,
        category="term_structure",
        summary=summary,
        table={"type": "term_structure", "rows": rows},
        facts=facts,
        numbers_used=numbers_used,
        limitations=_limitations_from(spot_obj, None),
    )


def _render_skew(state: AgentState) -> AnswerResponse:
    intent = state.intent
    assert intent is not None
    spot_obj = state.tool_outputs.get("spot")
    bundle = state.metrics.get("bundle")

    slope_res = getattr(bundle, "skew_slope", None)
    ts = getattr(bundle, "term_structure", None)
    slope = getattr(slope_res, "value", None)
    atm_strike = getattr(ts, "atm_strike", None)
    front_expiry = getattr(ts, "front_expiry", None)
    spot_value = spot_obj.snapshot.spot if spot_obj else None

    numbers_used: list[float] = []
    if spot_value is not None:
        numbers_used.append(float(spot_value))
    if atm_strike is not None:
        numbers_used.append(float(atm_strike))
    if slope is not None:
        numbers_used.append(float(slope))

    parts = []
    if intent.ticker:
        parts.append(f"{intent.ticker} skew slope:")
    if slope is not None and front_expiry is not None:
        parts.append(f"OLS slope {float(slope)} (IV vs strike) at front expiry {front_expiry}.")
    else:
        parts.append("skew slope unavailable (see Facts.flags).")
    summary = " ".join(parts)

    facts: dict[str, Any] = {
        "ticker": intent.ticker,
        "spot": _spot_fact(spot_obj),
        "right_used": state.metrics.get("right_used"),
        "front_expiry": str(front_expiry) if front_expiry else None,
        "atm_strike": atm_strike,
        "skew_slope": slope,
        "flags": list(getattr(slope_res, "flags", ()) or ()),
    }

    return _finalize(
        supported=True,
        category="skew",
        summary=summary,
        table={
            "type": "skew",
            "rows": [
                {
                    "front_expiry": str(front_expiry) if front_expiry else None,
                    "atm_strike": atm_strike,
                    "slope": slope,
                }
            ],
        },
        facts=facts,
        numbers_used=numbers_used,
        limitations=_limitations_from(spot_obj, None),
    )


def _render_greeks(state: AgentState) -> AnswerResponse:
    intent = state.intent
    assert intent is not None
    spot_obj = state.tool_outputs.get("spot")
    bundle = state.metrics.get("bundle")

    ag_res = getattr(bundle, "atm_greeks", None)
    snap = getattr(ag_res, "value", None)
    spot_value = spot_obj.snapshot.spot if spot_obj else None

    numbers_used: list[float] = []
    if spot_value is not None:
        numbers_used.append(float(spot_value))
    fields = ("strike", "iv", "delta", "gamma", "theta", "vega")
    row: dict[str, Any] = {}
    if snap is not None:
        row = {"option_symbol": snap.option_symbol, "expiry": str(snap.expiry)}
        for f in fields:
            v = getattr(snap, f)
            row[f] = v
            if v is not None:
                numbers_used.append(float(v))

    parts = []
    if intent.ticker:
        parts.append(f"{intent.ticker} ATM greeks:")
    if snap is not None:
        bits = []
        for f in fields:
            v = getattr(snap, f)
            if v is not None:
                bits.append(f"{f}={float(v)}")
        parts.append(" ".join(bits) + ".")
    else:
        parts.append("ATM greeks unavailable (see Facts.flags).")
    summary = " ".join(parts)

    facts: dict[str, Any] = {
        "ticker": intent.ticker,
        "spot": _spot_fact(spot_obj),
        "right_used": state.metrics.get("right_used"),
        "atm_contract": row,
        "flags": list(getattr(ag_res, "flags", ()) or ()),
    }

    return _finalize(
        supported=True,
        category="greeks",
        summary=summary,
        table={"type": "greeks", "rows": [row] if row else []},
        facts=facts,
        numbers_used=numbers_used,
        limitations=_limitations_from(spot_obj, None),
    )


# Not-supported and missing-ticker renderers ---------------------------------


_REWRITE_BY_REASON = {
    "advice": [
        "Show the option chain for [TICKER] front expiry around ATM, with bid/ask/mid.",
        "Compare ATM IV for [TICKER] front week vs next week.",
    ],
    "execution": [
        "Show ATM call and put for [TICKER] next week with bid/ask/mid.",
    ],
    "news": [
        "Compare ATM IV for [TICKER] front vs next expiry.",
        "Show IV skew for [TICKER] front expiry.",
    ],
    "portfolio": [
        "Show greeks for [TICKER] ATM contract front expiry.",
    ],
    "strategy": [
        "Show IV skew and ATM IV term structure for [TICKER].",
    ],
    "prediction": [
        "Show ATM IV term structure for [TICKER] over the next few expiries.",
    ],
}


def _render_not_supported(state: AgentState) -> AnswerResponse:
    intent = state.intent
    assert intent is not None
    reason = intent.not_supported_reason or "advice"
    rewrites = [
        r.replace("[TICKER]", intent.ticker or "your ticker")
        for r in _REWRITE_BY_REASON.get(reason, _REWRITE_BY_REASON["advice"])
    ]
    summary = (
        f"Not supported in scope: this question falls under '{reason}'. "
        "I can return data, not recommendations."
    )
    return _finalize(
        supported=False,
        category="not_supported",
        summary=summary,
        table={"type": "none", "rows": []},
        facts={"reason": reason, "ticker": intent.ticker},
        numbers_used=[],
        suggested_rewrites=rewrites,
    )


def _render_missing_ticker(state: AgentState) -> AnswerResponse:
    summary = (
        "I need a ticker to answer this. Please re-ask with the underlying "
        "(e.g., 'NVDA ATM IV this week vs next week')."
    )
    return _finalize(
        supported=False,
        category=state.intent.category if state.intent else "chain",
        summary=summary,
        table={"type": "none", "rows": []},
        facts={"missing": "ticker"},
        numbers_used=[],
    )


# Helpers --------------------------------------------------------------------


def _spot_fact(spot_obj: Any) -> dict[str, Any] | None:
    if spot_obj is None:
        return None
    snap = spot_obj.snapshot
    return {
        "value": float(snap.spot),
        "ts": str(snap.ts),
        "source": getattr(snap, "source", None),
    }


def _limitations_from(spot_obj: Any, quotes_obj: Any) -> list[str]:
    out: list[str] = []
    for obj in (spot_obj, quotes_obj):
        if obj is None:
            continue
        meta = getattr(obj, "meta", None)
        for w in getattr(meta, "warnings", []) or []:
            out.append(str(w))
    # de-dupe, keep order
    seen: set[str] = set()
    deduped: list[str] = []
    for w in out:
        if w not in seen:
            seen.add(w)
            deduped.append(w)
    return deduped


def _finalize(**kwargs: Any) -> AnswerResponse:
    """Run the no-invented-numbers guardrail then build the response."""

    summary: str = kwargs["summary"]
    allowed: list[float] = kwargs.get("numbers_used") or []
    bad = _allowed_numbers_in(summary, allowed)
    if bad:
        raise GuardrailViolation(
            f"Writer produced unsupported numeric tokens {bad} not present in "
            f"numbers_used {allowed}; refusing to emit."
        )
    return AnswerResponse(**kwargs)


def write(state: AgentState) -> AnswerResponse:
    """Stage 3: render the final answer."""

    if state.intent is None:
        # Defensive: planner skipped. Treat as missing ticker.
        return _render_missing_ticker(state)
    if state.intent.category == "not_supported":
        return _render_not_supported(state)
    if state.intent.ticker is None or "MISSING_TICKER" in state.errors:
        return _render_missing_ticker(state)

    cat = state.intent.category
    if cat == "chain":
        return _render_chain(state)
    if cat == "term_structure":
        return _render_term_structure(state)
    if cat == "skew":
        return _render_skew(state)
    if cat == "greeks":
        return _render_greeks(state)
    return _render_missing_ticker(state)
