# Polygon tools

Direct access to the Polygon-backed tool layer if you'd rather skip the
agent and just fetch data.

## Modules

```python
from oqe.tools.polygon_tools import (
    get_underlying_snapshot,
    list_option_contracts,
    get_option_quotes,
    get_option_greeks,
)
from oqe.tool_schemas import (
    GetUnderlyingSnapshotInput,
    ListOptionContractsInput,
    GetOptionQuotesInput,
    GetOptionGreeksInput,
)
```

## Get a spot snapshot

```python
from oqe.tools.polygon_tools import get_underlying_snapshot
from oqe.tool_schemas import GetUnderlyingSnapshotInput

resp = get_underlying_snapshot(GetUnderlyingSnapshotInput(ticker="NVDA"))
print(resp.snapshot.spot, resp.snapshot.ts, resp.snapshot.source)
print(resp.meta.warnings)              # ['STALE_DATA', ...] possibly
```

## List contracts (with optional filters)

```python
from oqe.tools.polygon_tools import list_option_contracts
from oqe.tool_schemas import ListOptionContractsInput
from datetime import date

resp = list_option_contracts(ListOptionContractsInput(
    ticker="NVDA",
    expiry=date(2026, 5, 16),
    right="C",
    strike_min=90,
    strike_max=110,
    limit=100,
))
for c in resp.contracts:
    print(c.option_symbol, c.strike, c.right)
```

## Quotes for a list of symbols

```python
from oqe.tools.polygon_tools import get_option_quotes
from oqe.tool_schemas import GetOptionQuotesInput

resp = get_option_quotes(GetOptionQuotesInput(option_symbols=[
    "O:NVDA260516C00100000",
    "O:NVDA260516P00100000",
]))
for q in resp.quotes:
    print(q.option_symbol, q.bid, q.ask, q.mid, q.ts)
```

## Greeks

```python
from oqe.tools.polygon_tools import get_option_greeks
from oqe.tool_schemas import GetOptionGreeksInput

resp = get_option_greeks(GetOptionGreeksInput(option_symbols=[
    "O:NVDA260516C00100000",
]))
for g in resp.greeks:
    print(g.option_symbol, g.iv, g.delta, g.gamma, g.theta, g.vega)
```

## Caching

Every tool above keys on `(tool_name, canonicalized_inputs, asof)` and
caches the response in `~/.oqe/cache.sqlite`:

| Tool | TTL |
| --- | --- |
| `get_underlying_snapshot` | 30s |
| `get_option_quotes` | 30s |
| `get_option_greeks` | 30s |
| `list_option_contracts` | 6h |

So calling the same tool twice within the TTL is free (no HTTP).

Override the cache path with `OQE_CACHE_PATH=/path/to/cache.sqlite`.

## Run-trace

If a `TraceLogger` is active (start one with `oqe.run_trace.start_trace()`
or pass `--trace` on the CLI), every tool call appends a JSON line to
`~/.oqe/traces/<trace_id>.jsonl`:

```jsonl
{"event": "tool_call", "tool": "get_option_greeks", "cache_key": "...", ...}
```

Useful for after-the-fact debugging.

## Errors

Tools may raise:

| Class | When |
| --- | --- |
| `PolygonAuthError` | Missing key, 401/403. |
| `PolygonNotFoundError` | 404 (e.g. unknown ticker). |
| `PolygonRateLimitError` | 429 after retries exhausted. |
| `PolygonHTTPError` | Other non-2xx. |
| `PolygonNetworkError` | Timeouts / connection errors. |

All inherit from `PolygonError`. The CLI catches them and renders the
themed error block.

## Lower level: PolygonHTTP / PolygonClient

If you need to talk to Polygon endpoints we don't yet wrap, the raw HTTP
layer is available:

```python
from oqe.polygon.http import PolygonHTTP

http = PolygonHTTP()
data = http.get_json("/v3/reference/options/contracts/O:NVDA260516C00100000")
```

`PolygonClient` adds pagination + a few typed convenience methods on top.

## See also

- [`oqe.tool_schemas`](https://github.com/playforest/options-query-agent/blob/main/src/oqe/tool_schemas.py) for full Pydantic input/output models.
- [Architecture: caching](../architecture/caching.md) for how the cache key is constructed.
