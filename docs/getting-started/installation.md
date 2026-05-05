# Installation

OQE is a Python 3.11+ package managed by [Poetry](https://python-poetry.org/).

## Prerequisites

- Python 3.11 or newer
- [Poetry](https://python-poetry.org/docs/#installation) (or `pip` if you'd rather)
- A [Polygon.io](https://polygon.io/) API key for live queries (the eval
  harness and most tests work fully offline)
- Optional: an Anthropic or OpenAI API key for the LLM-driven path
  (`oqe llm-ask` and the MCP server)

## Install with Poetry

The base install gets you the rule-based CLI (`oqe ask`), `oqe themes`,
the eval harness, and the Python API:

```bash
git clone https://github.com/playforest/options-query-agent
cd options-query-agent
poetry install
```

Optional extras enable specific features. Pick the ones you want:

| Extra | Enables | Install |
| --- | --- | --- |
| `plot` | `--plot PATH` (matplotlib charts) | `poetry install -E plot` |
| `anthropic` | Claude provider for `llm-ask` | `poetry install -E anthropic` |
| `openai` | GPT provider for `llm-ask` | `poetry install -E openai` |
| `llm` | Both LLM providers | `poetry install -E llm` |
| `mcp` | `oqe mcp-serve` (Claude Desktop / claude.ai web) | `poetry install -E mcp` |
| `docs` | `mkdocs serve` for the doc site | `poetry install --with docs` |

You can combine them, e.g. `poetry install -E llm -E mcp -E plot`.

!!! tip "Need the docs site too?"

    Install the optional `docs` group: `poetry install --with docs`. Then
    run `poetry run mkdocs serve` and open http://127.0.0.1:8000.

## Install with pip

If you'd rather not use Poetry:

```bash
pip install -e .              # base install
pip install -e ".[llm,mcp]"   # with LLM + MCP extras
```

(The `-e` makes it an editable install so source edits show up immediately.)

## Configure API keys

Copy the template and fill in the keys you need:

```bash
cp .env.example .env
```

Edit `.env`:

```bash
# Required for any live Polygon query (rule-based or LLM)
POLYGON_API_KEY=pk_your_polygon_key

# Required for `oqe llm-ask --provider anthropic` and the MCP server when
# chatting via Claude Desktop / claude.ai web
ANTHROPIC_API_KEY=sk-ant-your_anthropic_key

# Required for `oqe llm-ask --provider openai`
OPENAI_API_KEY=sk-your_openai_key
```

The CLI loads `.env` automatically on startup via `python-dotenv`. Anything
in your shell environment wins over `.env`, and `.env` wins over
`config.yaml`.

### Where to get the keys

| Variable | Provider | Sign up |
| --- | --- | --- |
| `POLYGON_API_KEY` | [Polygon.io](https://polygon.io/) | [polygon.io/dashboard/api-keys](https://polygon.io/dashboard/api-keys) |
| `ANTHROPIC_API_KEY` | [Anthropic](https://anthropic.com) | [console.anthropic.com](https://console.anthropic.com/settings/keys) |
| `OPENAI_API_KEY` | [OpenAI](https://openai.com) | [platform.openai.com](https://platform.openai.com/api-keys) |

### Optional LLM environment variables

| Variable | Effect | Default |
| --- | --- | --- |
| `OQE_LLM_PROVIDER` | Default LLM provider when `--provider` isn't passed | auto-detect (`anthropic` if `ANTHROPIC_API_KEY` set, else `openai`) |
| `OQE_LLM_MODEL` | Default model name when `--model` isn't passed | `claude-sonnet-4-6` (anthropic) / `gpt-4.1-mini` (openai) |

### Other useful env vars

| Variable | Effect | Default |
| --- | --- | --- |
| `POLYGON_HTTP_DEBUG` | Print every Polygon HTTP request on stderr | unset |
| `OQE_CACHE_PATH` | SQLite cache file | `~/.oqe/cache.sqlite` |
| `OQE_TRACE_DIR` | Where `--trace` writes JSONL + companion files | `~/.oqe/traces/` |
| `OQE_THEME` | Default colour theme | `bloomberg` |
| `OQE_LOG_LEVEL` | `DEBUG` / `INFO` / `WARNING` (default) / `ERROR` / `CRITICAL` | `WARNING` |
| `OQE_LOG_FORMAT` | `text` (themed when stderr is TTY) or `json` | `text` |
| `NO_COLOR` | Strip ANSI from all output | unset |

## Verify the install

=== "CLI"

    ```bash
    poetry run oqe --help
    ```

    ```text
    usage: oqe [-h] {ask,ask-many,llm-ask,mcp-serve,replay,themes} ...

    Options Query Engine - ask grounded questions about an options chain.

    positional arguments:
      {ask,ask-many,llm-ask,mcp-serve,replay,themes}
        ask         Ask a single natural-language question.
        ask-many    Run the same prompt against multiple tickers and compare results.
        llm-ask     Ask an LLM (Claude or GPT) using OQE tools as its data backend.
        mcp-serve   Run the OQE Model Context Protocol server over stdio.
        replay      Re-render a previously stored answer (companion JSON from --trace).
        themes      List or preview the colour themes.

    options:
      -h, --help    show this help message and exit
    ```

=== "Python"

    ```python
    from oqe.agent import answer_question
    print(answer_question.__module__)   # 'oqe.agent'
    ```

=== "Tests"

    ```bash
    poetry run python -m pytest -q
    ```

    ```text
    .................................................. [ 19%]
    .................................................. [ 39%]
    .................................................. [ 59%]
    .................................................. [ 79%]
    ....................................                [100%]
    253 passed in 1.7s
    ```

## Try it offline (no API key required)

The eval harness ships with a synthetic Polygon registry so you can confirm
the install end-to-end without a live key:

```bash
poetry run python eval/run_eval.py --no-color
```

```text
================================================================================
 OQE EVAL | 20 cases | 20 passed | 0 failed
================================================================================
[ RESULTS ]
PASS  tc_001    term_structure    NVDA ATM IV this week vs next week.
PASS  tc_002    term_structure    Compare ATM IV for SPY front week vs next ...
... (18 more) ...

[ BY CATEGORY ]
chain                 6/6
greeks                3/3
not_supported         4/4
skew                  3/3
term_structure        4/4
================================================================================
```

If that prints `0 failed`, you're ready to ask real questions.

## Next

- [Your first query](first-query.md) — a walkthrough
- [Concepts](concepts.md) — what the agent does and what it refuses
- [LLM-driven agent](../examples/llm-ask.md) — Claude / GPT with streaming
- [MCP server](../examples/mcp.md) — Claude Desktop / claude.ai integration
