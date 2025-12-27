# Reproducibility

This project aims to make tool results **repeatable**, **fast**, and **explainable**.

Reproducibility in v1 is achieved through:
- **Deterministic cache keys** (same logical request → same cache entry)
- **On-disk cache** (SQLite)
- **Explicit TTL policy** (freshness window per tool)
- **Run traces** (JSONL “flight recorder” of tool calls + sources)

> Live, step-by-step replay example: see `docs/notebooks/part4_replay_and_trace_walkthrough.ipynb`.

---

## Key terms

### “asof”
`asof` is an optional timestamp that means “answer as-of this time”.

In v1:
- `asof=None` means **latest**.
- For Polygon *snapshot* endpoints used in v1 tools, `asof` is **not supported** (latest-only).
  - If a caller supplies `asof`, tools return a `VENDOR_LIMIT` warning and still serve latest.

Future (Part 4/5):
- When we use endpoints that genuinely support historical time travel, `asof=<timestamp>` will request historical data, and TTL will be much longer.

---

## Cache

### What is cached
For each tool call, we compute a deterministic cache key from:

- `tool_name`
- canonicalized inputs (order-stable JSON)
- `asof` (normalized; `latest` if None)

We cache the **data payload** (not request-specific metadata), for example:
- `get_underlying_snapshot`: `snapshot` + base warnings
- `get_option_quotes`: `quotes_by_symbol` + base warnings
- `get_option_greeks`: `greeks_by_symbol` + base warnings

We do **not** cache:
- `ToolMeta.generated_at` (always “now”)
- request-specific warnings like `VENDOR_LIMIT` for unsupported `asof` (computed per request)

### TTL (time-to-live)
Each cache entry has:
- `created_at`
- `ttl_seconds`
- `expires_at = created_at + ttl_seconds`

When reading:
- if `now >= expires_at`, the entry is deleted and treated as a **cache miss**.

Tool TTL defaults are defined in `src/oqe/cache.py` (and can be tuned).

### Cache location
Default:
- `~/.oqe/cache.sqlite`

Override:
- set `OQE_CACHE_PATH` to point to a different sqlite file

Example:
```bash
export OQE_CACHE_PATH=/tmp/oqe-cache.sqlite
```

---

## Data source attribution

Each tool response includes `ToolMeta.primary_source` indicating where the returned data was served from:
- `"polygon"`: fetched from Polygon (vendor)
- `"cache"`: served from on-disk cache

Warnings (e.g., `STALE_DATA`, `PARTIAL_DATA`, `VENDOR_LIMIT`) appear in `ToolMeta.warnings`.

---

## Run traces (tool-call flight recorder)

A **trace** records what happened during a “run” (one question / one workflow).

Traces are stored as **JSONL** (one JSON object per line), containing:
- tool name
- canonical inputs JSON
- cache key
- primary_source (`polygon` or `cache`)
- warnings
- created_at timestamps

### Trace location
Default:
- `~/.oqe/traces/<trace_id>.jsonl`

Override:
- set `OQE_TRACE_DIR`

Example:
```bash
export OQE_TRACE_DIR=/tmp/oqe-traces
```

### How to start/end a trace (minimal)
```python
from oqe.run_trace import start_trace, end_trace

t = start_trace()  # or start_trace("my_trace_id")
# ... call tools ...
end_trace()

print(t.path)  # where JSONL was written
```

---

## How to replay / reproduce a run (detailed workflow)

### What “replay” means in v1
In v1, “replay” means: **reuse the same cached tool payloads** (and log that reuse in a new trace),
so the same tool inputs produce the same tool outputs (while the cache entries remain valid).

Because snapshot endpoints are *latest-only*, the key to reproducibility is preserving cache state.

### Replay workflow (CLI-level)
1) Identify the cache and trace from the original run:
- Cache: `~/.oqe/cache.sqlite` (or `OQE_CACHE_PATH`)
- Trace: `~/.oqe/traces/<trace_id>.jsonl` (or `OQE_TRACE_DIR`)

2) Freeze cache state by copying the SQLite DB:
```bash
cp ~/.oqe/cache.sqlite /tmp/replay-cache.sqlite
export OQE_CACHE_PATH=/tmp/replay-cache.sqlite
```

3) Re-run with the same tool inputs.
- If keys match and entries are not expired, responses will serve from cache.
- The new run will produce a new trace file capturing `primary_source="cache"`.

4) Compare traces:
```bash
diff -u ~/.oqe/traces/<old>.jsonl ~/.oqe/traces/<new>.jsonl
```

### Replay workflow (Notebook-level)
See `docs/notebooks/part4_replay_and_trace_walkthrough.ipynb` for a concrete, end-to-end example:
- run 1: vendor → cache write → trace
- run 2: cache hit → trace
- “new machine” simulation: copy cache DB + disable vendor → still serves from cache
