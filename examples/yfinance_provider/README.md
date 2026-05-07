# voli-yfinance

A reference [`DataProvider`](https://github.com/playforest/voli/blob/main/src/voli/providers/__init__.py)
implementation backed by [yfinance](https://github.com/ranaroussi/yfinance) —
the community-maintained Yahoo Finance scraper. Use it as a free, no-API-key
alternative to the bundled Polygon provider, or as a copy-paste template for
your own vendor.

## Install

From a Voli checkout:

```bash
pip install -e ./examples/yfinance_provider/
```

That installs `yfinance` and its deps and registers the provider via the
`voli.data_providers` entry point.

## Use

```bash
poetry run voli ask --data-provider yfinance "spot of NVDA"
poetry run voli ask --data-provider yfinance "NVDA ATM IV this week vs next week"

# Or persistently for the whole shell session:
export VOLI_DATA_PROVIDER=yfinance
poetry run voli ask "list NVDA calls for the nearest expiry"
```

Verify discovery:

```bash
poetry run python -c "from voli.providers import list_providers; print(list_providers())"
# -> ['polygon', 'yfinance']
```

## What works, what doesn't

| Capability | Status |
| --- | --- |
| Spot snapshot | ✅ via `Ticker.fast_info` / `Ticker.history` |
| Contracts list | ✅ via `Ticker.options` + `Ticker.option_chain(expiry)` |
| Quotes (bid / ask / last) | ✅ |
| Implied volatility | ✅ |
| Vendor delta / gamma / theta / vega | ❌ — yfinance doesn't publish them. Provider returns `None` for those fields and warns `PARTIAL_DATA`. |
| Historical asof replay | ❌ — yfinance is latest-only. Provider warns `VENDOR_LIMIT` if `asof` is set. |
| Open interest | available in raw data; not surfaced in this minimal example. |

Term structure, skew, and ATM-IV analytics work because they only need IV.
ATM-greeks-by-expiry will report partial data because vendor greeks are
absent.

## Caveats

- **yfinance breaks periodically.** It scrapes Yahoo Finance, which means
  Yahoo can break the API at any time. If your `voli ask` suddenly returns
  empty results, check the [yfinance issue tracker](https://github.com/ranaroussi/yfinance/issues)
  before blaming Voli.
- **Rate limits.** Yahoo will throttle aggressive callers. Voli's SQLite
  TTL cache (30s for quotes/greeks, 6h for contract lists) softens this; for
  tighter loops, consider a longer TTL.
- **Symbol convention.** yfinance returns OCC symbols without the `O:`
  prefix (e.g. `NVDA260516C00100000`). This adapter prepends `O:` so the
  symbols match Voli's existing convention end-to-end.

## Running the offline test

```bash
pip install pytest
pytest examples/yfinance_provider/tests/ -vv
```

The test suite mocks `yfinance.Ticker` so it runs without a network
connection.

## Layout

```
yfinance_provider/
├── pyproject.toml           # PEP 621 metadata + voli.data_providers entry point
├── README.md                # this file
├── voli_yfinance/
│   ├── __init__.py
│   └── provider.py          # the DataProvider implementation (~350 lines)
└── tests/
    └── test_yfinance_provider.py
```
