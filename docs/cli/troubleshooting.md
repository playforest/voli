# Troubleshooting

Real failure modes we've hit, with fixes. If you run into something else,
file an issue on GitHub with the trace ID (`voli ask --trace`).

## Missing API key

```text
================================================================================
 VOLI | ERROR: PolygonAuthError
================================================================================
[ MESSAGE ]
Missing POLYGON_API_KEY env var. Set it (or add to .env) before calling Polygon.
================================================================================
```

**Fix:** copy `.env.example` to `.env` and set your key:

```bash
cp .env.example .env
# Edit .env so it contains:
# POLYGON_API_KEY=pk_your_real_key
```

The CLI loads `.env` automatically on startup.

## Eval harness reports failures

```text
PASS  tc_001    term_structure    NVDA ATM IV this week vs next week.
FAIL  tc_002    term_structure    Compare ATM IV for SPY front week vs next ...
        -> facts.atm_strike: missing
        -> metric:atm_strike: missing (expected 500.0)
```

The eval runs against a synthetic registry, so a failure here is always a
regression in your code (planner, executor, analytics, or writer). Bisect:

1. `git log` for recent agent/analytics changes.
2. `poetry run python -m pytest tests/test_end_to_end.py::test_case[tc_002] -vv` for the per-case stack trace.
3. Re-run the whole eval after the fix — every category should be `passed/total` green.

## CLI hangs

The default behaviour fetches every page of the chain snapshot — for liquid
tickers that's typically 4-6 paginated requests, which can take 5-15s on a
slow connection. To see what it's actually doing:

```bash
POLYGON_HTTP_DEBUG=1 poetry run voli ask "NVDA ATM IV this week"
```

You'll see one log line per HTTP request:

```text
[polygon] -> GET https://api.polygon.io/v3/snapshot/options/NVDA params={...}
[polygon] <- 200 https://api.polygon.io/v3/snapshot/options/NVDA
[polygon] -> GET https://api.polygon.io/v3/snapshot/options/NVDA?cursor=...
[polygon] <- 200 https://api.polygon.io/v3/snapshot/options/NVDA?cursor=...
```

If a request is genuinely stuck (no `<-` line for >30s), it's network — try
again, or increase `POLYGON_HTTP_TIMEOUT` (in `config.yaml`).

## "Invalid limit" from Polygon

```text
Polygon HTTP 400: ... 'OptionsChainQueryParam.Limit' Error:Field validation
for 'Limit' failed on the 'max' tag
```

The chain snapshot endpoint caps `limit` at 250. We cap to 250 internally
in `voli.tools.polygon_tools`; if you see this error, you're probably on
an older revision. Pull `main`.

## Greeks validation error

```text
1 validation error for OptionGreeks
gamma
  Input should be greater than or equal to 0 [type=greater_than_equal,
  input_value=-3.1526505506027033e-10, ...]
```

Polygon occasionally emits tiny negative noise (`-3e-10`, `-8e-5`) for
gamma/vega — artefacts of an upstream Black-Scholes solver. We clamp
anything within `1e-3` of zero in `voli.polygon.normalise._clamp_nonneg`.
If you see this, you're on a revision before that fix; pull `main`.

## Output is monochrome / no colour

Possible causes:

| Symptom | Cause | Fix |
| --- | --- | --- |
| All commands plain | `NO_COLOR=1` in your shell | `unset NO_COLOR` |
| Plain only when piped | Auto-detection (correct behaviour) | Pass `--theme NAME` and accept the loss; pipes shouldn't carry ANSI. |
| Plain in tmux/screen | TTY detection differs | Force colour with `--theme NAME --no-color=false` (not currently supported — file an issue if you need this). |
| Some bold, no colour | Terminal doesn't support 256-color | Use a modern terminal (iTerm2, kitty, alacritty, modern Terminal.app/Linux GNOME Terminal). |

## "Show ATM call and put this Friday" → I need a ticker

```text
[ SUMMARY ]
I need a ticker to answer this. Please re-ask with the underlying (e.g.,
'NVDA ATM IV this week vs next week').
```

The planner couldn't extract a ticker from the prompt. Either include one in
the prompt, or pass `--ticker NAME`:

```bash
poetry run voli ask --ticker NVDA "Show ATM call and put this Friday"
```

## Refusal: my prompt should be supported

If `voli ask "..."` returns `REFUSED` and you think the question is in
scope, check the rewrites it suggested — they often re-frame the same
intent as a supported query. If it's a true false-positive, the planner's
keyword rules are too aggressive — open an issue with the prompt and we'll
tighten the heuristics.

The full taxonomy of supported vs not-supported lives in
[`docs/requirements.md`](https://github.com/playforest/voli/blob/main/docs/requirements.md).

## Stale data warning

```text
[ LIMITATIONS ]
! STALE_DATA
```

Polygon flagged the underlying snapshot as not real-time (delayed or
end-of-day). The agent still returns the data; you decide whether to use
it. Common after-hours, weekends, or on free-tier API plans.

## Next

- [CLI overview](overview.md) — flag reference
- [Examples](../examples/term-structure.md) — recipes that work
