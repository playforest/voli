# CLI usage

The `oqe` CLI is the v1 user surface. It wraps `oqe.agent.answer_question`
and prints the result in either Bloomberg-style ANSI text (default) or JSON.

## Install

```
poetry install
```

This registers the `oqe` script via `pyproject.toml`'s
`[tool.poetry.scripts]` entry. After install you can run it from the venv:

```
poetry run oqe ask "NVDA ATM IV this week vs next week"
```

## Commands

### `oqe ask "<prompt>"`

Ask a single natural-language question.

| Flag | Effect |
| --- | --- |
| `--ticker NVDA` | Default ticker if the prompt doesn't contain one. |
| `--asof 2026-05-05T15:00:00Z` | UTC as-of timestamp (best-effort, snapshot-dependent). Disclosed in the status bar and JSON payload. |
| `--json` | Emit JSON instead of the text view. |
| `--trace` | Open a JSONL run-trace under `$OQE_TRACE_DIR` (default `~/.oqe/traces/`). The trace ID is printed in the footer. |
| `--no-color` | Disable ANSI colour. Auto-disabled when stdout is not a TTY or when `NO_COLOR` is set in the environment. |

Exit codes:

| Code | Meaning |
| --- | --- |
| `0` | Supported question, answer rendered. |
| `3` | Refused (out of scope) or missing ticker. |
| `2` | Argparse error. |

## Examples

```bash
# Term structure (default text view)
poetry run oqe ask "NVDA ATM IV this week vs next week"

# Skew, JSON output, custom default ticker
poetry run oqe ask --ticker SPY --json "Show IV skew next Friday"

# Greeks with run-trace
poetry run oqe ask --trace "What are the greeks of the NVDA 2026-05-16 100C?"

# Pipe-friendly: colour auto-disables when stdout isn't a TTY
poetry run oqe ask "List NVDA calls for 2026-05-16" | head -40
```

## Output sections

For supported questions:

```
================================================================================
 OQE | TICKER: NVDA | CATEGORY: TERM_STRUCTURE | OK
================================================================================
[ SUMMARY ]
NVDA ATM IV term structure: front IV 0.4200 vs next IV 0.4500 ...

[ TERM STRUCTURE ]
EXPIRY      |  ATM STRIKE  |  ATM IV
------------+--------------+--------
2026-05-09  |       100.0  |  0.4200
2026-05-16  |       100.0  |  0.4500

[ FACTS ]
TICKER       NVDA
SPOT         value=102.5  ts=2026-05-05T12:34:56Z  source=polygon
RIGHT USED   call
ATM STRIKE   100.0
...
================================================================================
```

For refused (out-of-scope) questions:

```
[ SUMMARY ]
Not supported in scope: this question falls under 'execution'. ...

[ REASON ]
execution

[ TRY INSTEAD ]
> Show ATM call and put for NVDA next week with bid/ask/mid.
```

## Theme

The CLI uses 256-colour ANSI codes inspired by the Bloomberg Terminal:

| Element | Colour |
| --- | --- |
| Status bar / section headers | bold orange (ANSI 208) |
| Facts keys / column headers | amber (ANSI 214) |
| Values | terminal default white |
| Borders / dividers | dim gray (ANSI 240) |
| Warnings / refusals | bold red (ANSI 196) |

Set `NO_COLOR=1` or pass `--no-color` to strip ANSI sequences.
