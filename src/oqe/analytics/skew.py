"""Skew metrics.

Skew (v1) = how IV varies across strikes for a fixed expiry & right.
We support:
- strike->IV pairs (sorted)
- a simple slope metric (OLS fit of IV vs strike)

Missing data is surfaced via flags; we never fabricate IVs.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from .iv_metrics import MetricResult, _as_date, normalize_right


@dataclass(frozen=True)
class SkewCurve:
    expiry: date
    right: str
    pairs: tuple[tuple[float, float], ...]  # (strike, iv)
    flags: tuple[str, ...] = ()


def strike_iv_pairs(
    *,
    contracts: Sequence[object],
    greeks_by_symbol: Mapping[str, object],
    expiry: date | datetime | str,
    right: str,
) -> MetricResult[SkewCurve]:
    """Return (strike, iv) pairs for a single expiry/right.

    Assumes contract has attrs: expiry, strike, right, option_symbol (or symbol).
    Assumes greeks has attr: iv.

    Any contract whose IV is missing is skipped and flagged.
    """

    exp = _as_date(expiry)
    r = normalize_right(right)

    flags: list[str] = []
    pairs: list[tuple[float, float]] = []

    # Deterministic ordering: by strike, then option symbol.
    def _key(c: object) -> tuple[float, str]:
        sym = getattr(c, "option_symbol", None) or getattr(c, "symbol", None) or ""
        return (float(c.strike), sym)

    filtered = [c for c in contracts if _as_date(c.expiry) == exp and normalize_right(c.right) == r]

    if not filtered:
        return MetricResult(None, ("NO_CONTRACTS_FOR_EXPIRY_RIGHT",))

    for c in sorted(filtered, key=_key):
        sym = getattr(c, "option_symbol", None) or getattr(c, "symbol", None)
        if not sym:
            flags.append("MISSING_OPTION_SYMBOL")
            continue
        g = greeks_by_symbol.get(sym)
        if g is None:
            flags.append("MISSING_GREEKS")
            continue
        iv = getattr(g, "iv", None)
        if iv is None:
            flags.append("MISSING_IV")
            continue
        pairs.append((float(c.strike), float(iv)))

    if len(pairs) < 2:
        # Still return curve if we have 1 point, but slope won't be computable.
        flags.append("INSUFFICIENT_POINTS")

    # Deduplicate by strike keeping first (deterministic).
    seen: set[float] = set()
    dedup: list[tuple[float, float]] = []
    for k, v in pairs:
        if k in seen:
            flags.append("DUPLICATE_STRIKE")
            continue
        seen.add(k)
        dedup.append((k, v))

    curve = SkewCurve(
        expiry=exp, right=r, pairs=tuple(sorted(dedup, key=lambda kv: kv[0])), flags=tuple(flags)
    )
    return MetricResult(curve, tuple(flags))


def skew_slope_ols(pairs: Iterable[tuple[float, float]]) -> MetricResult[float]:
    """OLS slope of iv ~ strike.

    Uses closed-form simple linear regression:
      slope = cov(x,y) / var(x)

    Returns None if fewer than 2 points or var(x)=0.
    """

    pts = list(pairs)
    if len(pts) < 2:
        return MetricResult(None, ("INSUFFICIENT_POINTS",))

    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]

    n = len(xs)
    x_bar = sum(xs) / n
    y_bar = sum(ys) / n

    sxx = sum((x - x_bar) ** 2 for x in xs)
    if sxx == 0:
        return MetricResult(None, ("ZERO_STRIKE_VARIANCE",))

    sxy = sum((x - x_bar) * (y - y_bar) for x, y in zip(xs, ys, strict=False))
    return MetricResult(sxy / sxx, ())


def skew_slope(
    *,
    contracts: Sequence[object],
    greeks_by_symbol: Mapping[str, object],
    expiry: date | datetime | str,
    right: str,
) -> MetricResult[float]:
    """Convenience: compute strike->IV pairs then return OLS slope."""

    curve_res = strike_iv_pairs(
        contracts=contracts, greeks_by_symbol=greeks_by_symbol, expiry=expiry, right=right
    )
    if curve_res.value is None:
        return MetricResult(None, curve_res.flags)

    slope_res = skew_slope_ols(curve_res.value.pairs)
    # Keep curve flags (missing IV etc.) along with slope computation flags.
    flags = tuple(dict.fromkeys(curve_res.flags + slope_res.flags))
    return MetricResult(slope_res.value, flags)
