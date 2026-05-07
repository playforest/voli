# src/voli/models.py

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Right = Literal["C", "P"]
DataSource = Literal["polygon", "cache", "synthetic"]


def utc_now() -> datetime:
    return datetime.now(UTC)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class UnderlyingSnapshot(StrictModel):
    ticker: str = Field(min_length=1, description="Underlying ticker, e.g. NVDA")
    spot: float = Field(gt=0, description="Underlying last/spot price")
    ts: datetime = Field(description="Timestamp of snapshot (UTC)")
    source: DataSource

    @field_validator("ts")
    @classmethod
    def _ts_must_be_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("ts must be timezone-aware (UTC)")
        return v.astimezone(UTC)


class OptionContract(StrictModel):
    option_symbol: str = Field(min_length=1, description="Vendor option symbol (Polygon)")
    underlying: str = Field(min_length=1, description="Underlying ticker, e.g. NVDA")
    expiry: date = Field(description="Expiration date (YYYY-MM-DD)")
    strike: float = Field(gt=0, description="Strike price")
    right: Right = Field(description="'C' for call, 'P' for put")
    multiplier: int = Field(default=100, gt=0, description="Contract multiplier, typically 100")

    # Optional metadata we may or may not have from Polygon; keep optional for v1.
    currency: str | None = Field(default="USD", description="Quote currency if known")
    exercise_style: Literal["american", "european"] | None = Field(
        default=None, description="Exercise style if known"
    )


class OptionQuote(StrictModel):
    option_symbol: str = Field(min_length=1)
    bid: float | None = Field(default=None, ge=0)
    ask: float | None = Field(default=None, ge=0)
    last: float | None = Field(default=None, ge=0)
    mid: float | None = Field(default=None, ge=0, description="(bid+ask)/2 when both present")
    ts: datetime
    source: DataSource

    @model_validator(mode="after")
    def _compute_mid_if_missing(self) -> OptionQuote:
        if self.mid is None and self.bid is not None and self.ask is not None:
            return self.model_copy(update={"mid": (self.bid + self.ask) / 2.0})
        return self

    @field_validator("ts")
    @classmethod
    def _ts_must_be_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("ts must be timezone-aware (UTC)")
        return v.astimezone(UTC)


class OptionGreeks(StrictModel):
    option_symbol: str = Field(min_length=1)

    # Greeks are often missing depending on vendor / illiquidity.
    delta: float | None = Field(default=None, ge=-1, le=1)
    gamma: float | None = Field(default=None, ge=0)
    theta: float | None = Field(default=None)  # often negative
    vega: float | None = Field(default=None, ge=0)

    iv: float | None = Field(default=None, ge=0, description="Implied vol as DECIMAL, e.g. 0.42")

    ts: datetime
    source: DataSource

    # If we ever compute greeks ourselves, we’ll set this (else None).
    model: Literal["vendor", "black_scholes"] | None = Field(default=None)

    @field_validator("ts")
    @classmethod
    def _ts_must_be_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("ts must be timezone-aware (UTC)")
        return v.astimezone(UTC)
