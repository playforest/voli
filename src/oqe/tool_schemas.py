# src/oqe/tool_schemas.py
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, conlist, model_validator

from oqe.models import (
    DataSource,
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

WarningCode = Literal[
    "NO_RESULTS",
    "MARKET_CLOSED",
    "STALE_DATA",
    "PARTIAL_DATA",
    "VENDOR_LIMIT",
]

GreeksMode = Literal["vendor_only", "vendor_then_bs"]


class ToolMeta(StrictModel):
    """
    Standard metadata included in every tool response.
    """

    tool: ToolName = Field(description="Tool name")
    generated_at: ISODatetime = Field(description="When this response was produced (UTC)")
    asof: ISODatetime | None = Field(
        default=None, description="Requested asof timestamp (UTC) or None for latest"
    )
    primary_source: DataSource = Field(description="Primary datasource used")
    warnings: list[WarningCode] = Field(
        default_factory=list, description="Non-fatal issues / caveats"
    )


# tool: get_underlying_snapshot ----------
class GetUnderlyingSnapshotInput(StrictModel):
    model_config = StrictModel.model_config | {
        "json_schema_extra": {
            "description": "Fetch a spot/last price snapshot for an underlying ticker at an optional UTC time.",
            "examples": [{"ticker": "NVDA"}, {"ticker": "NVDA", "asof": "2025-12-25T00:00:00Z"}],
        }
    }

    ticker: str = Field(min_length=1, description="Underlying ticker, e.g. NVDA")
    asof: ISODatetime | None = Field(
        default=None,
        description="UTC timestamp (ISO-8601). If None, use latest available.",
    )


class GetUnderlyingSnapshotOutput(StrictModel):
    model_config = StrictModel.model_config | {
        "json_schema_extra": {
            "description": "Underlying snapshot result.",
            "examples": [
                {
                    "snapshot": {
                        "ticker": "NVDA",
                        "spot": 123.45,
                        "ts": "2025-12-25T00:00:00Z",
                        "source": "polygon",
                    }
                }
            ],
        }
    }
    meta: ToolMeta
    snapshot: UnderlyingSnapshot


# tool: list_option_contracts ----------
class ListOptionContractsInput(StrictModel):
    model_config = StrictModel.model_config | {
        "json_schema_extra": {
            "description": "List option contracts for an underlying with optional expiry/right/strike filters.",
            "examples": [
                {"ticker": "NVDA", "expiry": "2026-01-16", "right": "C", "limit": 200},
                {"ticker": "SPY", "strike_min": 400, "strike_max": 520, "limit": 500},
            ],
        }
    }

    ticker: str = Field(min_length=1, description="Underlying ticker, e.g. NVDA")
    expiry: ISODate | None = Field(default=None, description="Expiry date (YYYY-MM-DD)")
    right: Right | None = Field(default=None, description="'C' for calls, 'P' for puts")
    strike_min: float | None = Field(
        default=None, gt=0, description="Minimum strike (inclusive intent)"
    )
    strike_max: float | None = Field(
        default=None, gt=0, description="Maximum strike (inclusive intent)"
    )
    limit: int = Field(default=500, ge=1, le=5000, description="Max number of contracts to return")

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
    model_config = StrictModel.model_config | {
        "json_schema_extra": {
            "description": "Contracts matching the filters.",
            "examples": [
                {
                    "contracts": [
                        {
                            "option_symbol": "O:NVDA260116C00120000",
                            "underlying": "NVDA",
                            "expiry": "2026-01-16",
                            "strike": 120.0,
                            "right": "C",
                            "multiplier": 100,
                            "currency": "USD",
                            "exercise_style": "american",
                        }
                    ]
                }
            ],
        }
    }
    meta: ToolMeta
    contracts: list[OptionContract]


# tool: get_option_quotes ----------
class GetOptionQuotesInput(StrictModel):
    model_config = StrictModel.model_config | {
        "json_schema_extra": {
            "description": "Fetch bid/ask/last (and compute mid) for a list of option symbols at an optional UTC time.",
            "examples": [
                {"option_symbols": ["O:NVDA260116C00120000"]},
                {
                    "option_symbols": ["O:NVDA260116C00120000", "O:NVDA260116P00120000"],
                    "asof": "2025-12-25T00:00:00Z",
                },
            ],
        }
    }

    option_symbols: NonEmptySymbols = Field(description="List of option symbols (non-empty)")
    asof: ISODatetime | None = Field(
        default=None,
        description="UTC timestamp (ISO-8601). If None, use latest available.",
    )


class GetOptionQuotesOutput(StrictModel):
    model_config = StrictModel.model_config | {
        "json_schema_extra": {
            "description": "Quotes for the requested option symbols.",
            "examples": [
                {
                    "quotes": [
                        {
                            "option_symbol": "O:NVDA260116C00120000",
                            "bid": 10.0,
                            "ask": 10.5,
                            "last": 10.2,
                            "mid": 10.25,
                            "ts": "2025-12-25T00:00:00Z",
                            "source": "polygon",
                        }
                    ]
                }
            ],
        }
    }
    meta: ToolMeta
    quotes: list[OptionQuote]


# tool: get_option_greeks ----------
class GetOptionGreeksInput(StrictModel):
    model_config = StrictModel.model_config | {
        "json_schema_extra": {
            "description": "Fetch or compute greeks/IV for a list of option symbols at an optional UTC time.",
            "examples": [
                {"option_symbols": ["O:NVDA260116C00120000"]},
                {"option_symbols": ["O:NVDA260116C00120000"], "asof": "2025-12-25T00:00:00Z"},
            ],
        }
    }

    option_symbols: NonEmptySymbols = Field(description="List of option symbols (non-empty)")
    asof: ISODatetime | None = Field(
        default=None,
        description="UTC timestamp (ISO-8601). If None, use latest available.",
    )
    mode: GreeksMode = Field(
        default="vendor_only",
        description=(
            "How to source greeks. 'vendor_only' returns vendor greeks/IV when available. "
            "'vendor_then_bs' allows a fallback compute step (implemented later) if vendor greeks missing"
        ),
    )


class GetOptionGreeksOutput(StrictModel):
    model_config = StrictModel.model_config | {
        "json_schema_extra": {
            "description": "Greeks/IV for the requested option symbols.",
            "examples": [
                {
                    "greeks": [
                        {
                            "option_symbol": "O:NVDA260116C00120000",
                            "delta": 0.55,
                            "gamma": 0.02,
                            "theta": -0.10,
                            "vega": 0.12,
                            "iv": 0.42,
                            "ts": "2025-12-25T00:00:00Z",
                            "source": "polygon",
                            "model": "vendor",
                        }
                    ]
                }
            ],
        }
    }
    meta: ToolMeta
    greeks: list[OptionGreeks]


# tool: get_option_oi (optional) ----------
class GetOptionOIInput(StrictModel):
    model_config = StrictModel.model_config | {
        "json_schema_extra": {
            "description": "Fetch open interest for a list of option symbols (if available).",
            "examples": [{"option_symbols": ["O:NVDA260116C00120000"]}],
        }
    }

    option_symbols: NonEmptySymbols = Field(description="List of option symbols (non-empty)")


class OptionOI(StrictModel):
    model_config = StrictModel.model_config | {
        "json_schema_extra": {
            "description": "Open interest point for a single option symbol.",
            "examples": [
                {
                    "option_symbol": "O:NVDA260116C00120000",
                    "open_interest": 12345,
                    "ts": "2025-12-25T00:00:00Z",
                    "source": "polygon",
                }
            ],
        }
    }

    option_symbol: Symbol = Field(description="Option symbol")
    open_interest: int | None = Field(default=None, ge=0, description="Open interest if known")
    ts: ISODatetime | None = Field(default=None, description="UTC timestamp if known")
    source: Literal["polygon", "cache", "synthetic"] = Field(
        default="polygon",
        description="Where the value came from",
    )


class GetOptionOIOutput(StrictModel):
    model_config = StrictModel.model_config | {
        "json_schema_extra": {
            "description": "Open interest results for the requested option symbols.",
            "examples": [
                {"oi": [{"option_symbol": "O:NVDA260116C00120000", "open_interest": 12345}]}
            ],
        }
    }
    meta: ToolMeta
    oi: list[OptionOI]
