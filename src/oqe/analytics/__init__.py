# src/oqe/analytics/__init__.py
# ruff: noqa: F401

from __future__ import annotations

from .greeks import GreeksSnapshot, atm_greeks_for_expiry
from .iv_metrics import (
    MetricResult,
    TermStructureResult,
    atm_iv_term_structure,
    is_quote_spread_too_wide,
    is_spread_too_wide,
    mid_from_quote,
    mid_price,
    normalize_right,
    relative_spread,
    select_atm_strike,
)
from .metrics_bundle import MetricsBundle, compute_v1_metrics_bundle
from .protocols import OptionContractLike, OptionGreeksLike, OptionQuoteLike
from .skew import SkewCurve, delta_skew, skew_slope, skew_slope_ols, strike_iv_pairs

__all__ = [
    "GreeksSnapshot",
    "MetricResult",
    "MetricsBundle",
    "OptionContractLike",
    "OptionGreeksLike",
    "OptionQuoteLike",
    "SkewCurve",
    "TermStructureResult",
    "atm_greeks_for_expiry",
    "atm_iv_term_structure",
    "compute_v1_metrics_bundle",
    "delta_skew",
    "is_quote_spread_too_wide",
    "is_spread_too_wide",
    "mid_from_quote",
    "mid_price",
    "normalize_right",
    "relative_spread",
    "select_atm_strike",
    "skew_slope",
    "skew_slope_ols",
    "strike_iv_pairs",
]
