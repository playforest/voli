# Reproducibility

This project aims to make tool results **repeatable**, **fast**, and **explainable**.

Reproducibility in v1 is achieved through:
- **Deterministic cache keys** (same logical request → same cache entry)
- **On-disk cache** (SQLite)
- **Explicit TTL policy** (freshness window per tool)
- **Run traces** (JSONL “flight recorder” of tool calls + sources)

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