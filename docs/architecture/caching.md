# Caching

Voli ships a SQLite-backed cache so `voli ask "..."` for the same prompt
within a TTL window returns identical numbers without hitting Polygon.

## Where it lives

| Item | Default path | Override |
| --- | --- | --- |
| SQLite cache | `~/.voli/cache.sqlite` | `VOLI_CACHE_PATH` env var |

The path is created lazily on first write. Schema is initialized
automatically by `SQLiteCache.__init__`.

## TTL per tool

| Tool | TTL |
| --- | --- |
| `get_underlying_snapshot` | 30s |
| `get_option_quotes` | 30s |
| `get_option_greeks` | 30s |
| `list_option_contracts` | 6h |

Quotes / greeks / spot move quickly; contract listings rarely change
intra-session. TTLs are defined in `voli.cache.TOOL_TTL_LATEST_SECONDS`.

## Cache key construction

```python
key = sha256("v1|tool=<name>|asof=<asof>|inputs=<canonical_json>")
```

- `<name>` — the tool name (e.g. `get_option_quotes`).
- `<asof>` — `latest` for live snapshots, or a normalised ISO/epoch string.
- `<canonical_json>` — `voli.cache.canonical_json(inputs)`:
  - dict keys sorted recursively
  - certain list fields (e.g. `option_symbols`) sorted so order doesn't matter
  - `None` values dropped

This gives **deterministic cache keys**: same inputs (in any order) → same
key → same response.

## Reading + writing

```python
from voli.cache import SQLiteCache, default_cache_path, make_cache_key, ttl_for

cache = SQLiteCache(default_cache_path())
key, asof_norm, inputs_json = make_cache_key(
    "get_option_quotes",
    {"option_symbols": ["O:NVDA260516C00100000"]},
    asof=None,
)
record = cache.get(key)
if record is None:
    # ... fetch from Polygon ...
    cache.set(
        key=key,
        tool="get_option_quotes",
        asof=asof_norm,
        inputs_json=inputs_json,
        response_json='{"quotes_by_symbol": {...}}',
        ttl_seconds=ttl_for("get_option_quotes", asof_is_latest=True),
    )
```

`voli.tools.polygon_tools` does this dance for you — you don't normally call
the cache directly.

## Reproducibility

For any single prompt:

1. The planner is deterministic (same prompt → same `Plan`).
2. The executor's tool calls are cached; within the TTL the same inputs
   return the same payload.
3. Analytics are pure functions of their inputs.
4. The writer's output is deterministic given the same `AgentState`.

So: **same prompt + same TTL window = byte-identical answer.**

For strictly reproducible eval runs (no TTL race), point at the synthetic
registry from `voli.eval.synth_market` — that returns the same numbers
forever. The eval harness uses it by default.

## Trace files

`--trace` (or `start_trace()` in code) creates one JSONL file per CLI run
under `~/.voli/traces/<trace_id>.jsonl`. Each line is a `tool_call` event
with the cache key, inputs JSON, and warnings:

```jsonl
{"event": "trace_start", "trace_id": "20260505T130904Z_a1b2c3d4", ...}
{"event": "tool_call", "tool": "get_underlying_snapshot", "cache_key": "abc...", ...}
{"event": "tool_call", "tool": "list_option_contracts", "cache_key": "def...", ...}
{"event": "tool_call", "tool": "get_option_greeks", "cache_key": "ghi...", "primary_source": "cache", ...}
{"event": "trace_end", ...}
```

Override the trace dir with `VOLI_TRACE_DIR=/path/to/traces`.

## Invalidating the cache

There's no `voli cache clear` yet. Until there is:

```bash
rm ~/.voli/cache.sqlite
```

Or for tests / repeatable benchmarks:

```bash
VOLI_CACHE_PATH=/tmp/voli-test-cache.sqlite poetry run voli ask "..."
rm /tmp/voli-test-cache.sqlite
```

## See also

- [Reproducibility deep-dive](https://github.com/playforest/voli/blob/main/docs/reproducibility.md) — original Part 4 design notes.
- [Polygon tools](../python-api/tools.md) — where caching is wired in.
