"""Analytics / computation layer.

This package is intentionally pure (no API calls) and is the only place
finance math / deterministic metric definitions are implemented.
"""

from .iv_metrics import MetricResult

__all__ = ["MetricResult"]
