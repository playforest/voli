# src/oqe/analytics/protocols.py
from __future__ import annotations

from datetime import date, datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class OptionContractLike(Protocol):
    """Minimum shape required by analytics for an option contract.

    Note: analytics also expects a symbol identifier via either `.option_symbol` or `.symbol`.
    We intentionally don't require those attributes in this Protocol to avoid forcing
    models to implement both.
    """

    expiry: date | datetime | str
    strike: float
    right: str


@runtime_checkable
class OptionGreeksLike(Protocol):
    """Minimum shape required by analytics for greeks."""

    iv: float | None
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None


@runtime_checkable
class OptionQuoteLike(Protocol):
    """Minimum shape required by analytics for pricing/spread."""

    bid: float | None
    ask: float | None
    last: float | None
