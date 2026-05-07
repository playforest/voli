# Development guide

## Prereqs
- python = "^3.11"
- Poetry

## Setup
Install dependencies:
```bash
poetry install
```

(Optional, recommended) Install git hooks:
```bash
poetry run pre-commit install
```

## Running tests
Run the full suite:
```bash
poetry run python -m pytest
```

Quiet mode (CI-friendly):
```bash
poetry run python -m pytest -q
```

Verbose (shows file + test function names):
```bash
poetry run python -m pytest -v
```

Run a single test file:
```bash
poetry run python -m pytest tests/test_cache.py -vv
```

Run a single test function:
```bash
poetry run python -m pytest tests/test_cache.py::test_ttl_expiry_deletes_entry -vv
```

Show stdout/print output:
```bash
poetry run python -m pytest -vv -s
```

Show slowest tests:
```bash
poetry run python -m pytest -vv --durations=10
```

## Formatting / linting
```bash
poetry run ruff check .
poetry run black .
```

## Run all pre-commit hooks
```bash
poetry run pre-commit run --all-files
```

## Handy git alias: pre-commit + diff + commit (avoids “commit twice”)
If your pre-commit hooks auto-format files (ruff-format/black/etc.), your first `git commit` can fail because hooks modified files after staging.
This alias runs hooks first, shows what changed, restages, then commits.

Add the alias:
```bash
git config alias.pccommit '!f(){   git add -A &&   poetry run pre-commit run --all-files || exit $?;   echo "---- hook changes (unstaged) ----";   git diff --stat;   git diff;   git add -A;   git commit -v "$@"; }; f'
```

Use it:
```bash
git pccommit -m "your message"
```

## Inspecting the cache

Tool results are cached in a SQLite database. Useful when debugging stale data, TTLs, or unexpected cache misses.

**Default location:** `~/.voli/cache.sqlite` (override with `VOLI_CACHE_PATH`).
**Test runs:** `.pytest_voli_cache.sqlite` at the repo root, reset by `conftest.py` on every pytest run.

### Schema

Single table `cache_entries` (see `src/voli/cache.py`):

| column | type | meaning |
|---|---|---|
| `key` | TEXT (PK) | sha256 of `tool + canonical_inputs + asof` |
| `tool` | TEXT | tool name (e.g. `get_option_quotes`) |
| `asof` | TEXT | `latest` or normalized asof string |
| `inputs_json` | TEXT | canonicalized inputs |
| `response_json` | TEXT | tool response payload |
| `created_at` | REAL | unix epoch seconds at write time |
| `ttl_seconds` | INTEGER | TTL applied at write |
| `expires_at` | REAL | `created_at + ttl_seconds` |

### One-liners

`-header -column` makes output readable; treat `expires_at > strftime('%s','now')` as the "still fresh" predicate.

```bash
# count entries by tool
sqlite3 -header -column ~/.voli/cache.sqlite \
  "SELECT tool, COUNT(*) AS n FROM cache_entries GROUP BY tool;"

# list fresh entries with human-readable timestamps
sqlite3 -header -column ~/.voli/cache.sqlite \
  "SELECT tool, asof,
          datetime(created_at,'unixepoch') AS created,
          ttl_seconds,
          datetime(expires_at,'unixepoch') AS expires
   FROM cache_entries
   WHERE expires_at > strftime('%s','now')
   ORDER BY created_at DESC;"

# show one entry's payload, pretty-printed
sqlite3 ~/.voli/cache.sqlite \
  "SELECT response_json FROM cache_entries LIMIT 1;" \
  | python -m json.tool

# inspect a specific tool's most recent entry
sqlite3 -header -column ~/.voli/cache.sqlite \
  "SELECT key, asof, inputs_json, ttl_seconds
   FROM cache_entries
   WHERE tool='get_option_quotes'
   ORDER BY created_at DESC LIMIT 1;"

# wipe the cache (no schema change)
sqlite3 ~/.voli/cache.sqlite "DELETE FROM cache_entries;"
```

### Interactive REPL

```bash
sqlite3 ~/.voli/cache.sqlite
```

Then inside the prompt:

```
.headers on
.mode column
.schema cache_entries
SELECT tool, asof, ttl_seconds FROM cache_entries LIMIT 10;
.quit
```

> Note: never commit `~/.voli/cache.sqlite` or `.pytest_voli_cache.sqlite` — they're machine-local state, not source.
