# CLI overview

The `voli` script is registered by Poetry — once you've run `poetry install`
you can call it with `poetry run voli <command>`.

```text
$ poetry run voli --help
usage: voli [-h] {ask,ask-many,llm-ask,mcp-serve,replay,themes} ...

Voli - ask grounded questions about an options chain (chain
slice, IV term structure, skew, greeks).

positional arguments:
  {ask,ask-many,llm-ask,mcp-serve,replay,themes}
    ask         Ask a single natural-language question.
    ask-many    Run the same prompt against multiple tickers and compare
                results.
    llm-ask     Ask an LLM (Claude or GPT) using Voli tools as its data
                backend.
    mcp-serve   Run the Voli Model Context Protocol server over stdio.
    replay      Re-render a previously stored answer (companion JSON from
                --trace).
    themes      List or preview the colour themes.

options:
  -h, --help    show this help message and exit
```

## Quick subcommand map

| Command | Page |
| --- | --- |
| `voli ask` | This page (below). |
| `voli ask-many --tickers NVDA,SPY,QQQ "..."` | [Multi-ticker batching](../examples/batch.md) |
| `voli llm-ask "..."` | [LLM-driven agent](../examples/llm-ask.md) |
| `voli mcp-serve` | [MCP server (Claude Desktop)](../examples/mcp.md) |
| `voli replay <id>` | [Replay mode](../examples/replay.md) |
| `voli themes list / preview` | [Themes](themes.md) |

## `voli ask "<prompt>"`

The main command. Sends a prompt through the planner → executor → writer
pipeline and prints the result.

```text
$ poetry run voli ask --help
usage: voli ask [-h] [--ticker TICKER] [--asof ASOF] [--json] [--trace]
               [--theme NAME] [--cycle-theme] [--no-color]
               prompt

positional arguments:
  prompt                The question to ask, in quotes.

options:
  -h, --help            show this help message and exit
  --ticker TICKER       Default ticker if the prompt doesn't include one.
  --asof ASOF           UTC timestamp for as-of replay (best-effort,
                        snapshot-dependent).
  --json                Emit JSON instead of the themed text view.
  --trace               Open a JSONL run-trace under $VOLI_TRACE_DIR for this
                        question.
  --theme NAME          Colour theme. Default: bloomberg (or $VOLI_THEME).
  --cycle-theme         Pick the next theme in rotation (state in
                        ~/.voli/theme_cursor).
  --no-color            Disable ANSI colour. Auto-applied when stdout is not
                        a TTY.
```

### Flags reference

| Flag | Effect |
| --- | --- |
| `--ticker NAME` | Default ticker if the prompt doesn't contain one. Disclosed in Facts. |
| `--asof ISO8601` | UTC timestamp for as-of replay. Best-effort: not every snapshot endpoint supports historical replay. Always disclosed in the status bar. |
| `--json` | Emit a JSON object (see [Your first query](../getting-started/first-query.md#same-query-different-shapes)). |
| `--trace` | Open a JSONL run-trace under `$VOLI_TRACE_DIR` (default `~/.voli/traces/`). The trace ID appears in the footer. |
| `--theme NAME` | Pick a [bundled palette](themes.md). |
| `--cycle-theme` | Rotate to the next theme each invocation. Cursor stored at `~/.voli/theme_cursor`. |
| `--no-color` | Disable ANSI colour. Auto-disabled when stdout is not a TTY. |

### Selection precedence

For each setting that has multiple sources:

| Setting | Precedence (highest first) |
| --- | --- |
| Theme | `--cycle-theme` > `--theme NAME` > `$VOLI_THEME` > `bloomberg` |
| Colour | `--no-color` > `NO_COLOR` env var > stdout-is-TTY auto-detect |
| Ticker | Ticker in prompt > `--ticker` > error |
| API key | Process env var > `.env` > `config.yaml` > error |

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Supported question, answer rendered. |
| `2` | Argparse error (unknown flag, bad value). |
| `3` | Refused (out of scope) **or** missing ticker. |
| `4` | Upstream tool failure (Polygon, missing API key, etc.). Rendered as a themed error block. |

### Examples

=== "Term structure"

    ```bash
    poetry run voli ask "NVDA ATM IV this week vs next week"
    ```

=== "Skew with a custom theme"

    ```bash
    poetry run voli ask --theme matrix "Show NVDA IV skew next Friday"
    ```

=== "Greeks for a specific contract"

    ```bash
    poetry run voli ask "What are the greeks of the NVDA 2026-05-16 100C?"
    ```

=== "JSON for a script"

    ```bash
    poetry run voli ask --json "List NVDA calls for 2026-05-16" | jq '.facts'
    ```

=== "Run-trace"

    ```bash
    poetry run voli ask --trace "Show NVDA IV skew next Friday"
    # ... output ...
    cat ~/.voli/traces/<trace_id>.jsonl
    ```

=== "Refusal"

    ```bash
    poetry run voli ask "Should I buy NVDA calls?"
    # Exit code 3, themed REFUSED block, with rewrites.
    ```

## `voli themes`

```text
$ poetry run voli themes --help
usage: voli themes [-h] {list,preview} ...
```

See the [Themes page](themes.md) for full coverage.

## Environment variables

| Variable | Purpose | Default |
| --- | --- | --- |
| `POLYGON_API_KEY` | Polygon REST key. **Required for live queries.** | — |
| `POLYGON_HTTP_DEBUG` | Set to `1` to print every HTTP request/response on stderr. | unset |
| `VOLI_CACHE_PATH` | SQLite cache file. | `~/.voli/cache.sqlite` |
| `VOLI_TRACE_DIR` | Where `--trace` writes JSONL files. | `~/.voli/traces/` |
| `VOLI_THEME` | Default theme name. | `bloomberg` |
| `VOLI_THEME_CURSOR` | Cycle cursor file. | `~/.voli/theme_cursor` |
| `VOLI_LOG_LEVEL` | `DEBUG` / `INFO` / `WARNING` (default) / `ERROR` / `CRITICAL`. | `WARNING` |
| `VOLI_LOG_FORMAT` | `text` (themed when stderr is TTY) or `json`. | `text` |
| `VOLI_CONFIG` | Path to a `config.yaml` to load. | autodetect |
| `NO_COLOR` | Strip ANSI from all output. | unset |

## Config file

Anything you can set via env var, you can also set in `config.yaml`:

```yaml
default_theme: matrix
log_format: json
cache_path: /var/cache/voli.sqlite
```

See [`config.example.yaml`](https://github.com/playforest/voli/blob/main/config.example.yaml)
for every key.

## Next

- [Themes](themes.md) — pick a palette
- [Troubleshooting](troubleshooting.md) — common failure modes and fixes
