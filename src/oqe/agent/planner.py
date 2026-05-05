"""Heuristic planner: prompt -> Intent + Plan.

v1 deliberately uses regex/keyword rules rather than an LLM so that:
  - results are deterministic and trivially testable,
  - the unit tests don't need network or model access,
  - the contract from docs/v1_contract.md ("don't invent numbers") is easier to
    enforce.

A future Part 6.x could swap this module for an LLM-backed planner that emits
the same Intent/Plan shape.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .state import AgentState, Category, Intent, NotSupportedReason, Plan, PlanStep, Right

# A small whitelist is enough for v1 tests; anything else is parsed via regex
# (see _extract_ticker). We keep this list to bias the parser away from common
# English words ("ATM", "IV", "ETF") that look like tickers.
_KNOWN_TICKERS: tuple[str, ...] = (
    "NVDA",
    "SPY",
    "QQQ",
    "AAPL",
    "TSLA",
    "IWM",
    "MSFT",
    "AMZN",
    "META",
    "GOOG",
    "GOOGL",
    "NFLX",
    "AMD",
    "INTC",
)
_TICKER_STOPWORDS = {
    "ATM",
    "IV",
    "OTM",
    "ITM",
    "ET",
    "UTC",
    "API",
    "CLI",
    "FRI",
    "MON",
    "TUE",
    "WED",
    "THU",
    "SAT",
    "SUN",
    "JAN",
    "FEB",
    "MAR",
    "APR",
    "MAY",
    "JUN",
    "JUL",
    "AUG",
    "SEP",
    "OCT",
    "NOV",
    "DEC",
    "AND",
    "OR",
    "VS",
    "FOR",
    "THE",
    "OF",
    "TO",
}

_TICKER_RE = re.compile(r"\b([A-Z]{2,5})\b")
_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_DELTA_RE = re.compile(r"\b(\d{1,2})\s*[dD](?:elta)?\b")

# Keywords that put a prompt in the "Not supported" bucket. The mapping value
# is the reason category from docs/v1_contract.md so the writer can cite it.
_NOT_SUPPORTED_KEYWORDS: tuple[tuple[NotSupportedReason, tuple[str, ...]], ...] = (
    ("execution", ("buy", "sell", "execute", "place an order", "place order", "order to")),
    (
        "advice",
        (
            "should i",
            "recommend",
            "advise",
            "advice",
            "best contract",
            "best strike",
            "best spread",
            "what should",
        ),
    ),
    (
        "strategy",
        (
            "best spread",
            "iron condor",
            "strangle to",
            "straddle to trade",
            "credit spread",
            "debit spread",
        ),
    ),
    ("news", ("why did", "because of", "news", "earnings move", "due to")),
    ("portfolio", ("portfolio", "my account", "p&l", "pnl", "position size", "sizing", "hedge my")),
    ("prediction", ("predict", "will iv", "going to", "price target", "forecast")),
)


def _norm(text: str) -> str:
    return text.strip().lower()


def _extract_ticker(prompt: str) -> str | None:
    """Pick the most likely underlying ticker from the prompt.

    Strategy:
      1. A known ticker (case-insensitive word match) wins.
      2. Otherwise look for an uppercase token in the **original** prompt; this
         stops us from grabbing sentence-initial words like "Show" (which only
         look ticker-shaped after upper-casing the whole prompt).
    """

    upper = prompt.upper()
    for t in _KNOWN_TICKERS:
        if re.search(rf"\b{t}\b", upper):
            return t

    # Only consider tokens that the user wrote in uppercase already.
    for m in _TICKER_RE.finditer(prompt):
        cand = m.group(1)
        if cand in _TICKER_STOPWORDS:
            continue
        return cand
    return None


def _classify_not_supported(prompt: str) -> NotSupportedReason | None:
    p = _norm(prompt)
    for reason, keys in _NOT_SUPPORTED_KEYWORDS:
        for k in keys:
            if k in p:
                return reason
    return None


def _classify_supported(prompt: str) -> Category:
    """Choose between the four supported categories.

    Order matters: term-structure phrases ("term structure", "front vs next")
    should win over the more generic "iv". Skew phrases beat generic IV too.
    """

    p = _norm(prompt)

    if any(
        k in p
        for k in (
            "term structure",
            "term-structure",
            "front week vs",
            "this week vs next week",
            "front vs next",
            "front-month vs back-month",
            "atm iv",
            "iv this week vs",
            "iv front",
            "iv by expiry",
            "highest atm iv",
            "atm vega front",
        )
    ):
        # "ATM vega front week vs next week" is a Greeks comparison across
        # expiries; we keep that under term_structure since it pivots on expiry.
        greek_word = any(g in p for g in ("vega", "delta", "gamma", "theta"))
        if greek_word and "front" in p and ("vs" in p or "next" in p):
            return "term_structure"
        return "term_structure"

    if any(
        k in p
        for k in (
            "skew",
            "risk reversal",
            "25d put",
            "25 delta put",
            "25-delta put",
            "put iv vs call iv",
            "put vs call iv",
        )
    ):
        return "skew"

    if any(k in p for k in ("greek", "delta", "gamma", "theta", "vega")):
        return "greeks"

    # Anything mentioning IV without a more specific cue defaults to term
    # structure (the most common v1 IV question).
    if "iv" in p or "implied vol" in p:
        return "term_structure"

    # Default: chain lookup ("show", "list", "options expiring", "strikes around").
    return "chain"


def _classify_right(prompt: str) -> Right:
    p = _norm(prompt)
    has_call = bool(re.search(r"\bcalls?\b", p))
    has_put = bool(re.search(r"\bputs?\b", p))
    if has_call and not has_put:
        return "C"
    if has_put and not has_call:
        return "P"
    return "BOTH"


def _extract_target_delta(prompt: str) -> float | None:
    m = _DELTA_RE.search(prompt)
    if not m:
        return None
    n = int(m.group(1))
    if n <= 0 or n >= 100:
        return None
    return n / 100.0


def _expiry_phrase(prompt: str) -> str | None:
    p = _norm(prompt)
    iso = _ISO_DATE_RE.search(prompt)
    if iso:
        return iso.group(1)
    if "this friday" in p:
        return "this_friday"
    if "next friday" in p:
        return "next_friday"
    if "this week" in p:
        return "this_week"
    if "next week" in p:
        return "next_week"
    if "next monthly" in p or "next month" in p:
        return "next_monthly"
    if "nearest monthly" in p or "front monthly" in p or "front-month" in p:
        return "front_monthly"
    if "front week" in p or "front expiry" in p or "front-week" in p:
        return "front_week"
    return None


def parse_intent(prompt: str, *, ticker_default: str | None = None) -> Intent:
    """Public for tests: prompt -> Intent without building a Plan."""

    reason = _classify_not_supported(prompt)
    if reason is not None:
        return Intent(
            category="not_supported",
            ticker=_extract_ticker(prompt) or ticker_default,
            not_supported_reason=reason,
            raw_prompt=prompt,
        )

    ticker = _extract_ticker(prompt) or ticker_default
    return Intent(
        category=_classify_supported(prompt),
        ticker=ticker,
        right=_classify_right(prompt),
        expiry_phrase=_expiry_phrase(prompt),
        target_delta=_extract_target_delta(prompt),
        raw_prompt=prompt,
    )


# Plan factories --------------------------------------------------------------
#
# Each factory builds the deterministic tool sequence for one category. The
# executor will run steps in order; steps that need outputs from prior steps
# (e.g. quotes/greeks need the contract list) are wired by the executor using
# the `label` of the upstream step.


def _chain_plan(intent: Intent) -> Plan:
    assert intent.ticker is not None
    return Plan(
        steps=(
            PlanStep(
                tool="get_underlying_snapshot",
                inputs={"ticker": intent.ticker},
                label="spot",
            ),
            PlanStep(
                tool="list_option_contracts",
                inputs=_contract_inputs(intent),
                label="contracts",
            ),
            PlanStep(
                tool="get_option_quotes",
                inputs={"option_symbols_from": "contracts"},
                label="quotes",
            ),
        ),
        compute=None,
    )


def _term_structure_plan(intent: Intent) -> Plan:
    assert intent.ticker is not None
    return Plan(
        steps=(
            PlanStep(
                tool="get_underlying_snapshot",
                inputs={"ticker": intent.ticker},
                label="spot",
            ),
            PlanStep(
                tool="list_option_contracts",
                inputs=_contract_inputs(intent, default_right="C"),
                label="contracts",
            ),
            PlanStep(
                tool="get_option_greeks",
                inputs={"option_symbols_from": "contracts"},
                label="greeks",
            ),
        ),
        compute="term_structure",
    )


def _skew_plan(intent: Intent) -> Plan:
    assert intent.ticker is not None
    return Plan(
        steps=(
            PlanStep(
                tool="get_underlying_snapshot",
                inputs={"ticker": intent.ticker},
                label="spot",
            ),
            PlanStep(
                tool="list_option_contracts",
                inputs=_contract_inputs(intent, default_right="C"),
                label="contracts",
            ),
            PlanStep(
                tool="get_option_quotes",
                inputs={"option_symbols_from": "contracts"},
                label="quotes",
            ),
            PlanStep(
                tool="get_option_greeks",
                inputs={"option_symbols_from": "contracts"},
                label="greeks",
            ),
        ),
        compute="skew",
    )


def _greeks_plan(intent: Intent) -> Plan:
    assert intent.ticker is not None
    return Plan(
        steps=(
            PlanStep(
                tool="get_underlying_snapshot",
                inputs={"ticker": intent.ticker},
                label="spot",
            ),
            PlanStep(
                tool="list_option_contracts",
                inputs=_contract_inputs(intent, default_right="C"),
                label="contracts",
            ),
            PlanStep(
                tool="get_option_greeks",
                inputs={"option_symbols_from": "contracts"},
                label="greeks",
            ),
        ),
        compute="atm_greeks",
    )


def _contract_inputs(intent: Intent, *, default_right: str | None = None) -> dict:
    out: dict = {"ticker": intent.ticker, "limit": 500}
    if intent.right in ("C", "P"):
        out["right"] = intent.right
    elif default_right:
        out["right"] = default_right
    if intent.expiry_phrase and re.fullmatch(r"\d{4}-\d{2}-\d{2}", intent.expiry_phrase):
        out["expiry"] = intent.expiry_phrase
    return out


def _build_plan(intent: Intent) -> Plan:
    if intent.category == "not_supported" or intent.ticker is None:
        return Plan()
    if intent.category == "chain":
        return _chain_plan(intent)
    if intent.category == "term_structure":
        return _term_structure_plan(intent)
    if intent.category == "skew":
        return _skew_plan(intent)
    if intent.category == "greeks":
        return _greeks_plan(intent)
    return Plan()


def plan(state: AgentState, *, ticker_default: str | None = None) -> AgentState:
    """Stage 1: parse the prompt into Intent + Plan and attach to state."""

    intent = parse_intent(state.prompt, ticker_default=ticker_default)
    state.intent = intent
    state.plan = _build_plan(intent)
    if intent.ticker is None and intent.category != "not_supported":
        # Missing ticker is a special "ask the user" case; we record an error so
        # the writer can produce the disclosed clarification response.
        state.errors.append("MISSING_TICKER")
    return state


def supported_prompts() -> Iterable[str]:
    """Helper used by tests/eval to enumerate the v1 corpus categories."""

    return ("chain", "term_structure", "skew", "greeks")
