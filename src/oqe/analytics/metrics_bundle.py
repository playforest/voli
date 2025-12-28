# src/oqe/analytics/metrics_bundle.py
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .greeks import GreeksSnapshot, atm_greeks_for_expiry
from .iv_metrics import MetricResult, TermStructureResult, atm_iv_term_structure
from .skew import skew_slope


@dataclass(frozen=True)
class MetricsBundle:
    """Convenience container for the v1 metric outputs."""

    term_structure: TermStructureResult
    skew_slope: MetricResult[float]
    atm_greeks: MetricResult[GreeksSnapshot]


def compute_v1_metrics_bundle(
    *,
    spot: float,
    contracts: Iterable[Any],
    greeks_by_symbol: Mapping[str, Any],
    right: str,
) -> MetricsBundle:
    """
    Compute the v1 metric bundle for a given right ("call"/"put").

    v1 semantics:
    - Term structure: front expiry vs next expiry using the SAME strike (ATM strike from front grid).
    - Skew slope: computed on the front expiry.
    - ATM greeks: selected on the front expiry.

    All components surface missing-data via MetricResult flags; never fabricate values.
    """
    contracts_list = list(contracts)

    ts = atm_iv_term_structure(
        spot=spot,
        contracts=contracts_list,
        greeks_by_symbol=greeks_by_symbol,
        right=right,
    )

    front_expiry = ts.front_expiry
    if front_expiry is None:
        missing = MetricResult(None, ("MISSING_EXPIRY",))
        return MetricsBundle(term_structure=ts, skew_slope=missing, atm_greeks=missing)

    ss = skew_slope(
        contracts=contracts_list,
        greeks_by_symbol=greeks_by_symbol,
        expiry=front_expiry,
        right=right,
    )

    ag = atm_greeks_for_expiry(
        spot=spot,
        contracts=contracts_list,
        greeks_by_symbol=greeks_by_symbol,
        expiry=front_expiry,
        right=right,
    )

    return MetricsBundle(term_structure=ts, skew_slope=ss, atm_greeks=ag)
