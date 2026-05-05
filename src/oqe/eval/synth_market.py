"""Deterministic synthetic market for tests and the eval harness.

The real Polygon-backed registry isn't usable for repeatable tests (network
flakiness, market hours, key requirement). This module produces a ToolRegistry
that returns synthetic objects with the same attribute shapes and a
mathematical IV/quote surface that the eval dataset can assert against.

Design choices that the dataset relies on:
  * Spots are round numbers per ticker (NVDA=100, SPY=500, ...) so ATM strike
    selection is unambiguous.
  * Two expiries per ticker (front and next), 5 strikes each side of spot.
  * Front-week IV = 0.30 base; next-week adds +0.05; puts add +0.03;
    every 1pt away from spot adds +0.002 (smile). This makes ATM IVs
    exactly predictable.
  * Quotes have a uniform 1.00 wide spread (bid 1.00, ask 2.00, mid 1.50).
  * Greeks: delta = +/- 0.5, gamma = 0.02, theta = -0.10, vega = 0.12.

Anything that imports this module gets the same numbers - the eval dataset
encodes them as expected_metrics so a regression in the agent or analytics
shows up immediately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from oqe.agent.executor import ToolRegistry

# ---- shape stubs (mirror oqe.models / tool output structure) ---------------


@dataclass(frozen=True)
class _Snap:
    ticker: str
    spot: float
    ts: datetime
    source: str = "polygon"


@dataclass(frozen=True)
class _Meta:
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Resp:
    snapshot: _Snap | None = None
    contracts: list = field(default_factory=list)
    quotes: list = field(default_factory=list)
    greeks: list = field(default_factory=list)
    meta: _Meta = field(default_factory=_Meta)


@dataclass(frozen=True)
class _Contract:
    option_symbol: str
    expiry: date
    strike: float
    right: str  # "C" / "P"


@dataclass(frozen=True)
class _Quote:
    option_symbol: str
    bid: float | None
    ask: float | None
    mid: float | None
    last: float | None
    ts: datetime
    source: str = "polygon"


@dataclass(frozen=True)
class _Greeks:
    option_symbol: str
    iv: float | None
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None
    ts: datetime
    source: str = "polygon"


# ---- market parameters (reproduced in eval/prompts.jsonl) ------------------

SPOTS: dict[str, float] = {
    "NVDA": 100.0,
    "SPY": 500.0,
    "QQQ": 400.0,
    "AAPL": 200.0,
    "TSLA": 250.0,
    "IWM": 220.0,
    "MSFT": 410.0,
}

# Two expiries per ticker (front, next) - all on the same dates so the eval
# can refer to them without per-ticker bookkeeping.
EXPIRIES: tuple[date, date] = (date(2026, 5, 9), date(2026, 5, 16))

STRIKES_PER_SIDE = 5  # +/- 5 strikes around spot
STRIKE_STEP = 5.0


def expected_atm_strike(ticker: str) -> float:
    """ATM strike for a given ticker under the synthetic surface.

    Spots are deliberately round multiples of STRIKE_STEP so the closest
    strike is always exactly the spot.
    """

    return SPOTS[ticker]


def expected_iv(ticker: str, *, expiry_index: int, right: str, strike: float) -> float:
    """The IV surface formula. Mirrors `_make_stub_registry` below.

    expiry_index: 0 for front, 1 for next.
    right: 'C' or 'P'.
    strike: option strike.
    """

    spot = SPOTS[ticker]
    base = 0.30
    if expiry_index == 1:
        base += 0.05
    if right == "P":
        base += 0.03
    base += 0.002 * abs(strike - spot)
    return base


# ---- builder ----------------------------------------------------------------


def _build_chain() -> tuple[
    dict[str, _Snap],
    list[_Contract],
    dict[str, _Quote],
    dict[str, _Greeks],
]:
    """One-shot builder shared across every registry instance."""

    now = datetime.now(UTC)
    underlyings: dict[str, _Snap] = {
        t: _Snap(ticker=t, spot=spot, ts=now) for t, spot in SPOTS.items()
    }

    contracts: list[_Contract] = []
    quotes: dict[str, _Quote] = {}
    greeks: dict[str, _Greeks] = {}

    for ticker, spot in SPOTS.items():
        strikes = [spot + STRIKE_STEP * i for i in range(-STRIKES_PER_SIDE, STRIKES_PER_SIDE + 1)]
        for idx, exp in enumerate(EXPIRIES):
            for k in strikes:
                for right in ("C", "P"):
                    sym = f"O:{ticker}{exp.strftime('%y%m%d')}{right}{int(k * 1000):08d}"
                    contracts.append(_Contract(sym, exp, float(k), right))
                    quotes[sym] = _Quote(
                        option_symbol=sym,
                        bid=1.00,
                        ask=2.00,
                        mid=1.50,
                        last=1.50,
                        ts=now,
                    )
                    greeks[sym] = _Greeks(
                        option_symbol=sym,
                        iv=expected_iv(ticker, expiry_index=idx, right=right, strike=k),
                        delta=0.5 if right == "C" else -0.5,
                        gamma=0.02,
                        theta=-0.10,
                        vega=0.12,
                        ts=now,
                    )

    return underlyings, contracts, quotes, greeks


def make_registry() -> ToolRegistry:
    """Build a fresh ToolRegistry. Each call returns an independent instance
    (so callers that capture call logs don't interfere with each other).
    """

    underlyings, contracts, quotes_map, greeks_map = _build_chain()

    def _underlying(inp: dict[str, Any]) -> _Resp:
        snap = underlyings.get(inp["ticker"])
        if snap is None:
            return _Resp()
        return _Resp(snapshot=snap)

    def _list_contracts(inp: dict[str, Any]) -> _Resp:
        ticker = inp["ticker"]
        out = [c for c in contracts if c.option_symbol.startswith(f"O:{ticker}")]
        if "right" in inp:
            out = [c for c in out if c.right == inp["right"]]
        if "expiry" in inp:
            target = (
                date.fromisoformat(inp["expiry"])
                if isinstance(inp["expiry"], str)
                else inp["expiry"]
            )
            out = [c for c in out if c.expiry == target]
        return _Resp(contracts=out)

    def _quotes(inp: dict[str, Any]) -> _Resp:
        return _Resp(quotes=[quotes_map[s] for s in inp["option_symbols"] if s in quotes_map])

    def _greeks(inp: dict[str, Any]) -> _Resp:
        return _Resp(greeks=[greeks_map[s] for s in inp["option_symbols"] if s in greeks_map])

    return ToolRegistry(
        tools={
            "get_underlying_snapshot": _underlying,
            "list_option_contracts": _list_contracts,
            "get_option_quotes": _quotes,
            "get_option_greeks": _greeks,
        }
    )
