"""Analytics-level LLM tools.

The Stage A tools (`get_underlying_snapshot`, `list_option_contracts`,
`get_option_quotes`, `get_option_greeks`) give the LLM raw chain data and
let it work everything out by hand. That's flexible but token-heavy:
computing an ATM IV term structure means listing contracts, picking
expiries, grabbing greeks for each, finding ATM, etc - hundreds of
identifiers piped through the model just so it can do basic math.

These wrappers hide that plumbing. Each one:
  1. Calls the polygon tools to fetch the chain (snapshot + contracts +
     greeks, plus quotes when spread filtering is requested).
  2. Calls the corresponding pure function in `oqe.analytics`.
  3. Returns a flat JSON object the LLM can quote directly.

The on-disk SQLite cache makes the repeated polygon calls cheap; the
model never sees the intermediate identifiers.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from oqe.analytics.greeks import atm_greeks_for_expiry
from oqe.analytics.iv_metrics import atm_iv_term_structure
from oqe.analytics.skew import skew_slope
from oqe.tool_schemas import GetUnderlyingSnapshotInput
from oqe.tools.polygon_tools import (
    get_option_chain_bulk,
    get_underlying_snapshot,
)

from .types import ToolDef

# ---------------------------------------------------------------------------
# Shared chain-fetch helper
# ---------------------------------------------------------------------------


def _normalise_right(right: str | None) -> str:
    if right is None:
        return "call"
    r = right.strip().lower()
    if r in ("c", "call", "calls"):
        return "call"
    if r in ("p", "put", "puts"):
        return "put"
    return r  # let analytics surface flag if it's invalid


def _right_filter(right_word: str) -> str | None:
    return "C" if right_word == "call" else "P" if right_word == "put" else None


def _fetch_chain(
    *,
    ticker: str,
    right_word: str,
    expiry: str | None = None,
    include_quotes: bool = False,
) -> tuple[float, list, dict, dict]:
    """Return (spot, contracts, greeks_by_symbol, quotes_by_symbol).

    `right_word` must be normalised ("call" / "put"). `expiry` is an
    ISO YYYY-MM-DD string or None.

    Implementation note: previously this fetched contracts, then iterated
    one HTTP request per symbol to get greeks - 30+ seconds for liquid
    chains (INTC / SPY / AAPL) which blew past MCP's request timeout.
    Now uses `get_option_chain_bulk` which pulls contracts + quotes +
    greeks together from Polygon's chain snapshot in a single paginated
    call. `include_quotes` only controls whether we *return* quotes to
    the caller; the bulk fetch grabs them either way (cheap, no extra
    HTTP) so spread filtering and price questions stay fast.
    """

    snap = get_underlying_snapshot(GetUnderlyingSnapshotInput(ticker=ticker))
    if snap is None or getattr(snap, "snapshot", None) is None:
        return 0.0, [], {}, {}
    spot = float(snap.snapshot.spot)

    rf = _right_filter(right_word)
    contracts, quotes_by_symbol, greeks_by_symbol = get_option_chain_bulk(
        ticker=ticker,
        right=rf,
        expiry=expiry,
    )

    if not contracts:
        return spot, [], {}, {}

    if not include_quotes:
        quotes_by_symbol = {}

    return spot, contracts, greeks_by_symbol, quotes_by_symbol


def _err(message: str, **extra: Any) -> str:
    return json.dumps({"error": message, **extra})


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def _tool_compute_atm_iv_term_structure(args: dict[str, Any]) -> str:
    ticker = args.get("ticker")
    if not ticker:
        return _err("missing_ticker")
    right_word = _normalise_right(args.get("right"))
    max_spread = args.get("max_relative_spread")

    spot, contracts, greeks, quotes = _fetch_chain(
        ticker=ticker,
        right_word=right_word,
        include_quotes=max_spread is not None,
    )
    if not contracts:
        return _err("no_contracts", ticker=ticker)

    result = atm_iv_term_structure(
        spot=spot,
        contracts=contracts,
        greeks_by_symbol=greeks,
        right=right_word,
        quotes_by_symbol=quotes if max_spread is not None else None,
        max_relative_spread=max_spread,
    )

    iv_diff = None
    if result.front_iv is not None and result.next_iv is not None:
        iv_diff = round(result.next_iv - result.front_iv, 6)

    payload = {
        "ticker": ticker,
        "spot": spot,
        "right": right_word,
        "atm_strike": result.atm_strike,
        "front_expiry": result.front_expiry.isoformat()
        if isinstance(result.front_expiry, date)
        else None,
        "next_expiry": result.next_expiry.isoformat()
        if isinstance(result.next_expiry, date)
        else None,
        "front_iv": result.front_iv,
        "next_iv": result.next_iv,
        "iv_diff": iv_diff,
        "flags": list(result.flags),
    }
    if max_spread is not None:
        payload["max_relative_spread"] = max_spread
    return json.dumps(payload, default=str)


def _tool_compute_skew_slope(args: dict[str, Any]) -> str:
    ticker = args.get("ticker")
    if not ticker:
        return _err("missing_ticker")
    right_word = _normalise_right(args.get("right"))
    expiry = args.get("expiry")
    max_spread = args.get("max_relative_spread")

    spot, contracts, greeks, quotes = _fetch_chain(
        ticker=ticker,
        right_word=right_word,
        expiry=expiry,
        include_quotes=max_spread is not None,
    )
    if not contracts:
        return _err("no_contracts", ticker=ticker)

    # If the caller didn't pin an expiry, default to the front expiry on
    # the right side - same convention the rule-based agent uses.
    target_expiry: Any = expiry
    if target_expiry is None:
        ts = atm_iv_term_structure(
            spot=spot,
            contracts=contracts,
            greeks_by_symbol=greeks,
            right=right_word,
        )
        if ts.front_expiry is None:
            return _err("no_front_expiry", ticker=ticker, flags=list(ts.flags))
        target_expiry = ts.front_expiry

    slope_res = skew_slope(
        contracts=contracts,
        greeks_by_symbol=greeks,
        expiry=target_expiry,
        right=right_word,
        quotes_by_symbol=quotes if max_spread is not None else None,
        max_relative_spread=max_spread,
    )

    payload = {
        "ticker": ticker,
        "spot": spot,
        "right": right_word,
        "expiry": target_expiry.isoformat() if isinstance(target_expiry, date) else target_expiry,
        "skew_slope": slope_res.value,
        "flags": list(slope_res.flags),
    }
    if max_spread is not None:
        payload["max_relative_spread"] = max_spread
    return json.dumps(payload, default=str)


def _tool_get_atm_greeks(args: dict[str, Any]) -> str:
    ticker = args.get("ticker")
    if not ticker:
        return _err("missing_ticker")
    right_word = _normalise_right(args.get("right"))
    expiry = args.get("expiry")

    spot, contracts, greeks, _ = _fetch_chain(
        ticker=ticker,
        right_word=right_word,
        expiry=expiry,
        include_quotes=False,
    )
    if not contracts:
        return _err("no_contracts", ticker=ticker)

    target_expiry: Any = expiry
    if target_expiry is None:
        ts = atm_iv_term_structure(
            spot=spot,
            contracts=contracts,
            greeks_by_symbol=greeks,
            right=right_word,
        )
        if ts.front_expiry is None:
            return _err("no_front_expiry", ticker=ticker, flags=list(ts.flags))
        target_expiry = ts.front_expiry

    snap_res = atm_greeks_for_expiry(
        spot=spot,
        contracts=contracts,
        greeks_by_symbol=greeks,
        expiry=target_expiry,
        right=right_word,
    )
    snap = snap_res.value
    payload: dict[str, Any] = {
        "ticker": ticker,
        "spot": spot,
        "right": right_word,
        "expiry": target_expiry.isoformat() if isinstance(target_expiry, date) else target_expiry,
        "flags": list(snap_res.flags),
    }
    if snap is not None:
        payload["atm"] = {
            "option_symbol": snap.option_symbol,
            "strike": snap.strike,
            "iv": snap.iv,
            "delta": snap.delta,
            "gamma": snap.gamma,
            "theta": snap.theta,
            "vega": snap.vega,
        }
    return json.dumps(payload, default=str)


# ---------------------------------------------------------------------------
# JSON schemas (inline; small, no Pydantic models needed)
# ---------------------------------------------------------------------------


_TICKER_PROP = {"type": "string", "description": "Underlying ticker, e.g. NVDA"}
_RIGHT_PROP = {
    "type": "string",
    "enum": ["call", "put"],
    "description": "Option right. Default: call.",
}
_EXPIRY_PROP = {
    "type": "string",
    "description": "Expiry date YYYY-MM-DD. If omitted, defaults to the front (earliest) expiry.",
}
_SPREAD_PROP = {
    "type": "number",
    "description": (
        "Optional bid-ask spread filter (e.g. 0.20 for 20%). When set, "
        "contracts whose relative spread exceeds the threshold are excluded "
        "from the calculation."
    ),
}


def build_analytics_tools() -> list[ToolDef]:
    """Higher-level analytics tools the LLM should prefer over chaining the
    raw polygon tools by hand.
    """

    return [
        ToolDef(
            name="compute_atm_iv_term_structure",
            description=(
                "Compute the ATM implied-volatility term structure for an "
                "underlying. Returns front expiry IV, next expiry IV, the "
                "ATM strike used, and the IV diff. Prefer this over manually "
                "chaining list_option_contracts + get_option_greeks for any "
                "'ATM IV this week vs next week' style question."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "ticker": _TICKER_PROP,
                    "right": _RIGHT_PROP,
                    "max_relative_spread": _SPREAD_PROP,
                },
                "required": ["ticker"],
                "additionalProperties": False,
            },
            fn=_tool_compute_atm_iv_term_structure,
        ),
        ToolDef(
            name="compute_skew_slope",
            description=(
                "Compute the OLS slope of IV vs strike (the skew slope) for "
                "a given expiry. If expiry is omitted, defaults to the front "
                "expiry. Negative slope = downside skew (puts richer); positive "
                "slope = upside skew. Prefer this for any 'how steep is the "
                "skew' question."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "ticker": _TICKER_PROP,
                    "right": _RIGHT_PROP,
                    "expiry": _EXPIRY_PROP,
                    "max_relative_spread": _SPREAD_PROP,
                },
                "required": ["ticker"],
                "additionalProperties": False,
            },
            fn=_tool_compute_skew_slope,
        ),
        ToolDef(
            name="get_atm_greeks",
            description=(
                "Get the at-the-money contract's greeks (iv, delta, gamma, "
                "theta, vega) for a given expiry/right. If expiry is omitted, "
                "defaults to the front expiry. Prefer this over manually "
                "calling get_option_greeks on a list of symbols when the user "
                "only cares about ATM."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "ticker": _TICKER_PROP,
                    "right": _RIGHT_PROP,
                    "expiry": _EXPIRY_PROP,
                },
                "required": ["ticker"],
                "additionalProperties": False,
            },
            fn=_tool_get_atm_greeks,
        ),
    ]
