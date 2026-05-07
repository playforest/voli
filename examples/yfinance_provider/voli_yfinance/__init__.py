"""yfinance data provider for Voli.

Drop-in alternative to the bundled Polygon provider. Install with::

    pip install -e examples/yfinance_provider/

Then::

    voli ask --data-provider yfinance "spot of NVDA"
"""

from .provider import YFinanceProvider

__all__ = ["YFinanceProvider"]
