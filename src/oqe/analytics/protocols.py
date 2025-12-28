# src/oqe/analytics/protocols.py
from __future__ import annotations

from datetime import date, datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class OptionContractLike(Protocol):
    """Minimum shape required by analytics for an option contract."""

    expiry: date | datetime | str
    strike: float
    right: str

    # at least one of these must exist
    option_symbol: str  # noqa: SIM905 - protocol attribute
    # symbol: str  # optional alternative supported via getattr


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
