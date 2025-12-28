# src/oqe/analytics/metrics_bundle.py
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from .greeks import ATMGreeksResult, atm_greeks_for_expiry
from .iv_metrics import TermStructureResult, atm_iv_term_structure
from .skew import SkewSlopeResult, skew_slope


@dataclass(frozen=True)
class MetricsBundle:
    """Convenience container for the v1 metric outputs."""

    term_structure: TermStructureResult
    skew_slope: SkewSlopeResult
    atm_greeks: ATMGreeksResult


def compute_v1_metrics_bundle(
    *,
    spot: float,
    contracts: Iterable[Any],
    greeks_by_symbol: Mapping[str, Any],
    right: str,
) -> MetricsBundle:
    """
    Compute the v1 metric bundle for a given right ("call"/"put").
    - Term structure uses front vs next expiry and same strike.
    - Skew slope uses the front expiry (if available).
    - ATM greeks uses the front expiry (if available).
    """
    ts = atm_iv_term_structure(
        spot=spot,
        contracts=contracts,
        greeks_by_symbol=greeks_by_symbol,
        right=right,
    )

    # For skew + ATM greeks we focus on the front expiry (v1)
    front_expiry = ts.front_expiry

    if front_expiry is None:
        # If we can't find expiries, keep deterministic Nones + flags
        ss = SkewSlopeResult(expiry=date.min, right=right, slope=None, flags=("MISSING_EXPIRY",))
        ag = ATMGreeksResult(
            expiry=date.min,
            right=right,
            atm_strike=ts.atm_strike,
            greeks=None,
            flags=("MISSING_EXPIRY",),
        )
        return MetricsBundle(term_structure=ts, skew_slope=ss, atm_greeks=ag)

    ss = skew_slope(
        contracts=contracts,
        greeks_by_symbol=greeks_by_symbol,
        expiry=front_expiry,
        right=right,
    )

    ag = atm_greeks_for_expiry(
        spot=spot,
        contracts=contracts,
        greeks_by_symbol=greeks_by_symbol,
        expiry=front_expiry,
        right=right,
    )

    return MetricsBundle(term_structure=ts, skew_slope=ss, atm_greeks=ag)
