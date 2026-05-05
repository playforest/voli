# Replay mode

When you run `oqe ask --trace`, the CLI now also writes a companion
`<trace_id>.response.json` alongside the existing JSONL trace. `oqe replay`
reads that companion and re-renders the answer — no Polygon round-trip,
deterministic, lets you pivot themes / output formats / view the same
answer hours or days later.

## Trace, then replay

```bash
# Capture
poetry run oqe ask --trace --ticker NVDA "ATM IV this week vs next week"
# ... themed output ...
# replay companion: ~/.oqe/traces/20260505T150131Z_2096073f.response.json

# Replay, same theme
poetry run oqe replay 20260505T150131Z_2096073f

# Replay in a different theme
poetry run oqe replay --theme matrix 20260505T150131Z_2096073f

# Replay as JSON for tooling
poetry run oqe replay --json 20260505T150131Z_2096073f
```

You can also pass an absolute path to the companion file:

```bash
poetry run oqe replay /tmp/traces/my-saved.response.json
```

## Why a separate companion file?

The JSONL trace file (`<trace_id>.jsonl`) is a flight recorder — one line
per tool call with cache key, vendor warnings, and `asof_norm`. Useful
for debugging *what happened*. Replay needs the *finished answer* — one
structured JSON object — so the renderer can recreate the CLI output
without re-running tool dispatch.

Storing them side-by-side keeps both formats clean:

```
~/.oqe/traces/20260505T150131Z_2096073f.jsonl          ← tool calls
~/.oqe/traces/20260505T150131Z_2096073f.response.json  ← finished answer
```

## Companion JSON shape

```json
{
  "trace_id": "20260505T150131Z_2096073f",
  "prompt": "ATM IV this week vs next week",
  "ticker_default": "NVDA",
  "asof": null,
  "theme": "bloomberg",
  "skeptic": false,
  "response": {
    "supported": true,
    "category": "term_structure",
    "summary": "NVDA ATM IV term structure: front IV 0.3 vs next IV 0.35 ...",
    "table":  {"type": "term_structure", "rows": [...]},
    "facts":  {"ticker": "NVDA", "spot": {...}, ...},
    "numbers_used": [100.0, 0.30, 0.35, 0.05],
    "limitations": [],
    "suggested_rewrites": [],
    "skeptic": null
  }
}
```

## Programmatic

```python
from oqe.replay import dump_response, load_replay, replay_to_response

# Persist your own answer (e.g. from a batch job that doesn't use --trace)
from oqe.agent import answer_question
resp = answer_question("ATM IV this week vs next week", ticker_default="NVDA")
dump_response("my-saved", resp, prompt="ATM IV this week vs next week",
              ticker_default="NVDA", theme="bloomberg")

# Read it back as a typed AnswerResponse
rebuilt = replay_to_response("my-saved")
print(rebuilt.summary)

# Or just inspect the raw JSON payload
payload = load_replay("my-saved")
print(payload["prompt"], payload["response"]["category"])
```

## Override the trace dir

The companion lives under whatever `OQE_TRACE_DIR` resolves to (default
`~/.oqe/traces/`). For tests / sandboxed runs:

```bash
OQE_TRACE_DIR=/tmp/oqe-replays poetry run oqe ask --trace --ticker NVDA \
  "ATM IV this week vs next week"
```

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Replay rendered successfully. |
| `3` | The replayed answer was a refusal or missing-ticker. |
| `4` | Companion JSON not found at the supplied id/path. |

## See also

- [Caching](../architecture/caching.md) — how the trace and cache layers fit together.
- [Plotting](plotting.md) — pair `--plot` with `--trace` for a chart + replay-able JSON.
