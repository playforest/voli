# CLI usage

The `voli` CLI is the v1 user surface. It wraps `voli.agent.answer_question`
and prints the result in either Bloomberg-style ANSI text (default) or JSON.

## Install

```
poetry install
```

This registers the `voli` script via `pyproject.toml`'s
`[tool.poetry.scripts]` entry. After install you can run it from the venv:

```
poetry run voli ask "NVDA ATM IV this week vs next week"
```

## Commands

### `voli ask "<prompt>"`

Ask a single natural-language question.

| Flag | Effect |
| --- | --- |
| `--ticker NVDA` | Default ticker if the prompt doesn't contain one. |
| `--asof 2026-05-05T15:00:00Z` | UTC as-of timestamp (best-effort, snapshot-dependent). Disclosed in the status bar and JSON payload. |
| `--json` | Emit JSON instead of the text view. |
| `--trace` | Open a JSONL run-trace under `$VOLI_TRACE_DIR` (default `~/.voli/traces/`). The trace ID is printed in the footer. |
| `--no-color` | Disable ANSI colour. Auto-disabled when stdout is not a TTY or when `NO_COLOR` is set in the environment. |
| `--theme NAME` | Pick a colour theme. See `voli themes list` for the names. Default is `bloomberg` (or `$VOLI_THEME`). |
| `--cycle-theme` | Pick the next theme in rotation each invocation. Cursor is stored at `~/.voli/theme_cursor` (override with `$VOLI_THEME_CURSOR`). |

### `voli themes list`

Print every bundled theme with its description, each row themed in its own
palette so you can see what you're choosing.

### `voli themes preview [--theme NAME | --all]`

Render a sample answer in the chosen theme. `--all` renders the same sample
once per theme so you can compare them side-by-side.

Exit codes:

| Code | Meaning |
| --- | --- |
| `0` | Supported question, answer rendered. |
| `3` | Refused (out of scope) or missing ticker. |
| `2` | Argparse error. |

## Examples

```bash
# Term structure (default text view)
poetry run voli ask "NVDA ATM IV this week vs next week"

# Skew, JSON output, custom default ticker
poetry run voli ask --ticker SPY --json "Show IV skew next Friday"

# Greeks with run-trace
poetry run voli ask --trace "What are the greeks of the NVDA 2026-05-16 100C?"

# Pipe-friendly: colour auto-disables when stdout isn't a TTY
poetry run voli ask "List NVDA calls for 2026-05-16" | head -40
```

## Output sections

For supported questions:

```
================================================================================
 VOLI | TICKER: NVDA | CATEGORY: TERM_STRUCTURE | OK
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

## Themes

Twelve bundled palettes (run `voli themes list` to see them with live samples):

| Name | Vibe |
| --- | --- |
| `bloomberg` (default) | Orange + amber on black, classic Bloomberg Terminal |
| `bloomberg_classic` | Deeper, slightly desaturated Bloomberg variant |
| `matrix` | Phosphor green on black |
| `amber_crt` | Vintage amber-monochrome CRT |
| `solarized_dark` | Yellow accent, base0 body, blue highlights |
| `dracula` | Purple + pink on dark grey |
| `nord` | Cool frost-blues, low contrast |
| `cyberpunk` | Neon pink primary, cyan accents |
| `mono` | Greyscale only - works on any terminal |
| `paper` | Inverted, dark inks for light terminals |
| `sepia` | Aged photograph: warm browns + cream on near-black |
| `material` | MkDocs Material dark code: pink keywords, purple modules, soft green strings on dark blue-grey |

Selection precedence: `--cycle-theme` > `--theme NAME` > `$VOLI_THEME` > `bloomberg`.

```bash
poetry run voli ask --theme matrix "NVDA ATM IV this week vs next week"
VOLI_THEME=dracula poetry run voli ask "Show NVDA IV skew next Friday"
poetry run voli ask --cycle-theme "Show NVDA IV skew"   # rotates each call
poetry run voli themes preview --all                     # see every palette
```

Set `NO_COLOR=1` or pass `--no-color` to strip ANSI sequences entirely.
