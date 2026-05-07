# Extending Voli — data providers

Voli ships with a [Polygon.io](https://polygon.io/) data provider. To plug in
a different vendor (yfinance, Tradier, IBKR, ORATS, Theta Data, a synthetic
fixture, ...) you implement four small fetcher methods and register them.
The cache, run-trace, response envelope, and "no invented numbers" guardrail
all stay in Voli core — your job is just the vendor I/O and normalisation.

## What you implement

`voli.providers.DataProvider` is a [Protocol](https://docs.python.org/3/library/typing.html#typing.Protocol),
not an abstract base class — duck-typing works. The full surface:

```python
from voli.models import OptionContract, OptionGreeks, OptionQuote
from voli.providers import DataProvider  # Protocol, for type hints only


class MyProvider:
    name: str = "myprov"   # appears in ToolMeta.primary_source

    def fetch_underlying_snapshot(self, ticker, *, asof=None):
        """Return ({"ticker", "spot", "ts", "source"}, warnings_list)."""
        ...

    def fetch_option_contracts(
        self, ticker, *, right=None, expiry=None,
        strike_min=None, strike_max=None, limit=500,
    ):
        """Return ([OptionContract, ...], warnings_list)."""
        ...

    def fetch_option_quotes(self, option_symbols, *, asof=None):
        """Return ({symbol: OptionQuote, ...}, warnings_list)."""
        ...

    def fetch_option_greeks(self, option_symbols, *, asof=None, mode="vendor_only"):
        """Return ({symbol: OptionGreeks, ...}, warnings_list)."""
        ...

    # OPTIONAL — implement for fast analytics (one chain pull instead of N
    # per-symbol calls). Return None if your vendor can't do it in one shot.
    def fetch_option_chain_bulk(
        self, ticker, *, right=None, expiry=None, max_pages=20,
    ):
        """Return (contracts_list, quotes_by_symbol, greeks_by_symbol) or None."""
        ...
```

Voli's domain models are defined in `voli.models`; warnings are short string
codes (`"NO_RESULTS"`, `"PARTIAL_DATA"`, `"STALE_DATA"`, `"VENDOR_LIMIT"`)
documented in `voli.tool_schemas.WarningCode`.

## Hello-world: a 30-line MockProvider

Save as `mock_provider.py`:

```python
from datetime import UTC, date, datetime

from voli.models import OptionContract, OptionGreeks, OptionQuote


class MockProvider:
    name = "mock"

    def fetch_underlying_snapshot(self, ticker, *, asof=None):
        return (
            {
                "ticker": ticker,
                "spot": 100.0,
                "ts": "2026-01-01T00:00:00Z",
                "source": self.name,
            },
            [],
        )

    def fetch_option_contracts(self, ticker, *, right=None, expiry=None, **_):
        sym = f"O:{ticker}260116C00100000"
        return (
            [
                OptionContract(
                    option_symbol=sym,
                    underlying=ticker,
                    expiry=date(2026, 1, 16),
                    strike=100.0,
                    right="C",
                )
            ],
            [],
        )

    def fetch_option_quotes(self, option_symbols, *, asof=None):
        ts = datetime.now(UTC)
        return (
            {
                s: OptionQuote(option_symbol=s, bid=2.0, ask=2.1, ts=ts, source=self.name)
                for s in option_symbols
            },
            [],
        )

    def fetch_option_greeks(self, option_symbols, *, asof=None, mode="vendor_only"):
        ts = datetime.now(UTC)
        return (
            {
                s: OptionGreeks(
                    option_symbol=s, delta=0.5, iv=0.3, ts=ts, source=self.name
                )
                for s in option_symbols
            },
            [],
        )
```

Register and try it:

```python
import voli.providers as providers
from mock_provider import MockProvider

providers.register("mock", MockProvider())
providers.set_active("mock")

from voli.tool_schemas import GetUnderlyingSnapshotInput
from voli.tools.polygon_tools import get_underlying_snapshot

print(get_underlying_snapshot(GetUnderlyingSnapshotInput(ticker="NVDA")))
```

Or from the CLI:

```bash
VOLI_DATA_PROVIDER=mock poetry run voli ask "spot of NVDA"
# (after register() runs in a sitecustomize.py or your package init)
```

## Shipping as a pip-installable package

The delightful path. Once your `MyProvider` works in-tree, wrap it in a tiny
package so users can `pip install voli-yourvendor` and have the provider
auto-discovered.

`pyproject.toml`:

```toml
[project]
name = "voli-tradier"
version = "0.1.0"
dependencies = ["voli>=0.1", "httpx>=0.28"]

[project.entry-points."voli.data_providers"]
tradier = "voli_tradier.provider:TradierProvider"
```

Or with Poetry:

```toml
[tool.poetry]
name = "voli-tradier"
version = "0.1.0"

[tool.poetry.dependencies]
python = "^3.11"
voli = "^0.1"
httpx = "^0.28"

[tool.poetry.plugins."voli.data_providers"]
tradier = "voli_tradier.provider:TradierProvider"
```

After `pip install voli-tradier`:

```bash
poetry run python -c "from voli.providers import list_providers; print(list_providers())"
# -> ['polygon', 'tradier']

poetry run voli ask --data-provider tradier "30d ATM IV on NVDA"
```

The entry-point string can resolve to:

- A **class** — Voli instantiates it with no args and registers the instance.
- An **instance** — Voli registers it as-is.

If the import or instantiation raises, Voli logs nothing and skips the
provider rather than crashing the CLI — a broken third-party plugin can't
take down a Polygon user's flow.

## Sharp edges

- **OCC vs vendor option symbols.** Voli's analytics expect option symbols in
  the OCC-like form `O:NVDA260516C00100000` (used by Polygon and most US
  brokers). If your vendor exposes raw OCC (`NVDA260516C00100000`) prepend
  the `O:` in your normaliser. If your vendor uses a totally different
  scheme (e.g. IBKR conid), translate at the provider boundary.
- **Timestamps must be UTC tz-aware.** `OptionQuote.ts` and friends raise on
  naive datetimes. Use `datetime.now(timezone.utc)` or `astimezone(UTC)` in
  your normaliser.
- **Greeks are optional.** If your vendor doesn't publish vendor greeks, set
  the fields to `None` and append `"PARTIAL_DATA"` to the warnings list.
  Don't compute Black-Scholes in the provider — that's Voli's job (mode
  `vendor_then_bs`, planned for a future release).
- **Implement `fetch_option_chain_bulk` if you can.** The analytics layer
  (term structure, skew slope, ATM greeks) issues one bulk call per chain.
  Per-symbol fallback works but turns sub-second answers into 30+ second
  ones on liquid names like SPY.
- **Don't manage caching yourself.** Voli wraps every fetcher in the SQLite
  TTL cache, keyed on canonicalised inputs. Returning fresh data every call
  is fine; Voli decides when to skip you.

## Reference: the bundled Polygon provider

Read [`src/voli/providers/polygon.py`](https://github.com/playforest/voli/blob/main/src/voli/providers/polygon.py)
end-to-end — it's about 250 lines and shows every piece of a real adapter
(HTTP client management, normalisation from raw rows, partial-data handling,
bulk fetch). New providers can mirror its structure almost line-for-line.

## See also

- [LLM providers](llm-providers.md) — the same plug-and-play story for
  Anthropic / OpenAI / your-LLM-of-choice.
- [Architecture: orchestrator](../architecture/orchestrator.md) — where the
  provider sits in the request lifecycle.
- [`voli.providers` source](https://github.com/playforest/voli/blob/main/src/voli/providers/__init__.py) — the full Protocol + registry implementation.
