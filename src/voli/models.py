# src/voli/models.py

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Right = Literal["C", "P"]
# DataSource is a free string so third-party providers (yfinance, tradier, ...)
# can stamp their own name without widening a Literal here. Voli's bundled
# Polygon provider sets source="polygon"; the cache layer overrides to "cache".
DataSource = str


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

    @model_validator(mode="before")
    @classmethod
    def _compute_mid_if_missing(cls, data):
        # Auto-fill `mid` when caller passes bid+ask but no explicit mid. Runs
        # `mode="before"` so we can mutate the input dict — the equivalent
        # `mode="after"` pattern returning `model_copy(...)` is silently
        # discarded by pydantic >= 2.10 on frozen models.
        if isinstance(data, dict) and data.get("mid") is None:
            bid = data.get("bid")
            ask = data.get("ask")
            if bid is not None and ask is not None:
                data["mid"] = (float(bid) + float(ask)) / 2.0
        return data

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


class NewsItem(StrictModel):
    """A news article tagged to one or more tickers.

    Voli's news surface is intentionally minimal: identifier, when it was
    published, what it says, who said it, where to read it, and which
    tickers it's tagged with. Anything richer (sentiment, embeddings,
    keywords) belongs in a downstream analytics layer, not in the data
    model itself.
    """

    id: str = Field(min_length=1, description="Vendor-stable article ID")
    published_utc: datetime = Field(description="Publish time (UTC)")
    title: str = Field(min_length=1, description="Article headline")
    article_url: str = Field(min_length=1, description="Canonical article URL")
    publisher: str = Field(min_length=1, description="Publisher name (e.g. 'Bloomberg')")
    tickers: list[str] = Field(
        default_factory=list,
        description="Tickers tagged on this article by the vendor",
    )
    description: str | None = Field(
        default=None, description="Short summary or lede if vendor provides one"
    )
    author: str | None = Field(default=None, description="Byline if available")
    source: DataSource

    @field_validator("published_utc")
    @classmethod
    def _published_must_be_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("published_utc must be timezone-aware (UTC)")
        return v.astimezone(UTC)
