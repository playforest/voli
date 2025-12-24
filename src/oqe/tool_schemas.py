# src/oqe/tool_schemas.py
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, conlist, model_validator

from oqe.models import (
    OptionContract,
    OptionGreeks,
    OptionQuote,
    Right,
    StrictModel,
    UnderlyingSnapshot,
)

ISODate = date
ISODatetime = datetime

Symbol = Annotated[str, StringConstraints(min_length=1)]
NonEmptySymbols = conlist(Symbol, min_length=1)

ToolName = Literal[
    "get_underlying_snapshot",
    "list_option_contracts",
    "get_option_quotes",
    "get_option_greeks",
    "get_option_oi",
]


# tool: get_underlying_snapshot ----------
class GetUnderlyingSnapshotInput(StrictModel):
    ticker: str = Field(min_length=1)
    asof: ISODatetime | None = Field(
        default=None, description="UTC timestamp; if None, use latest available"
    )


class GetUnderlyingSnapshotOutput(StrictModel):
    snapshopt: UnderlyingSnapshot


# tool: list_option_contracts ----------
class ListOptionContractsInput(StrictModel):
    ticker: str = Field(min_length=1)
    expiry: ISODate | None = None
    right: Right | None = None
    strike_min: float | None = Field(default=None, gt=0)
    strike_max: float | None = Field(default=None, gt=0)
    limit: int = Field(default=500, ge=1, le=5000)

    @model_validator(mode="after")
    def _strike_range_ok(self) -> ListOptionContractsInput:
        if (
            self.strike_min is not None
            and self.strike_max is not None
            and self.strike_min > self.strike_max
        ):
            raise ValueError("strike_min must be <= strike_max")
        return self


class ListOptionContractsOutput(StrictModel):
    contracts: list[OptionContract]


# tool: get_option_quotes ----------
class GetOptionQuotesInput(StrictModel):
    option_symbols: NonEmptySymbols = Field(description="List of option symbols (non-empty)")
    asof: ISODatetime | None = None


class GetOptionQuotesOutput(StrictModel):
    quotes: list[OptionQuote]


# tool: get_option_greeks ----------
class GetOptionGreeksInput(StrictModel):
    option_symbols: NonEmptySymbols = Field(description="List of option symbols (non-empty)")
    asof: ISODatetime | None = None


class GetOptionGreeksOutput(StrictModel):
    greeks: list[OptionGreeks]


# tool: get_option_oi (optional) ----------
class GetOptionOIInput(StrictModel):
    option_symbols: NonEmptySymbols = Field(description="List of option symbols (non-empty)")


class OptionOI(StrictModel):
    option_symbol: str
    open_interest: int | None = Field(default=None, ge=0)
    ts: ISODatetime | None = None
    source: Literal["polygon", "cache", "synthetic"] = "polygon"


class GetOptionOIOutput(StrictModel):
    oi: list[OptionOI]
