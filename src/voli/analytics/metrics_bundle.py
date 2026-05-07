# src/voli/analytics/metrics_bundle.py
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .greeks import GreeksSnapshot, atm_greeks_for_expiry
from .iv_metrics import MetricResult, TermStructureResult, atm_iv_term_structure
from .protocols import OptionContractLike, OptionGreeksLike, OptionQuoteLike
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
    contracts: Iterable[OptionContractLike],
    greeks_by_symbol: Mapping[str, OptionGreeksLike],
    right: str,
    quotes_by_symbol: Mapping[str, OptionQuoteLike] | None = None,
    max_relative_spread: float | None = None,
    exclude_if_spread_unknown: bool = True,
    tie_break: str = "lower",
) -> MetricsBundle:
    """Compute the v1 metric bundle for a given right ("call"/"put").

    If quotes_by_symbol and max_relative_spread are provided, spread filtering is applied
    to term structure and skew slope computations.
    """
    contracts_list = list(contracts)

    ts = atm_iv_term_structure(
        spot=spot,
        contracts=contracts_list,
        greeks_by_symbol=greeks_by_symbol,
        right=right,
        quotes_by_symbol=quotes_by_symbol,
        max_relative_spread=max_relative_spread,
        exclude_if_spread_unknown=exclude_if_spread_unknown,
        tie_break=tie_break,
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
        quotes_by_symbol=quotes_by_symbol,
        max_relative_spread=max_relative_spread,
        exclude_if_spread_unknown=exclude_if_spread_unknown,
    )

    # v1: ATM greeks selection does NOT depend on quotes; it depends on the strike grid.
    ag = atm_greeks_for_expiry(
        spot=spot,
        contracts=contracts_list,
        greeks_by_symbol=greeks_by_symbol,
        expiry=front_expiry,
        right=right,
        tie_break=tie_break,
    )

    return MetricsBundle(term_structure=ts, skew_slope=ss, atm_greeks=ag)
