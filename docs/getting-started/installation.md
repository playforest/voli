# Installation

OQE is a Python 3.11+ package managed by [Poetry](https://python-poetry.org/).

## Prerequisites

- Python 3.11 or newer
- [Poetry](https://python-poetry.org/docs/#installation) (or `pip` if you'd rather)
- A [Polygon.io](https://polygon.io/) API key for live queries (the eval
  harness and most tests work fully offline)

## Install with Poetry

```bash
git clone https://github.com/playforest/options-query-agent
cd options-query-agent
poetry install
```

This installs the runtime deps (httpx, pydantic, python-dotenv, pyyaml) and
registers the `oqe` console script.

!!! tip "Need the docs site too?"

    Install the optional `docs` group: `poetry install --with docs`. Then
    run `poetry run mkdocs serve` and open http://127.0.0.1:8000.

## Install with pip

If you'd rather not use Poetry:

```bash
pip install -e .
```

(The `-e` makes it an editable install so source edits show up immediately.)

## Configure your Polygon key

Copy the template and fill in your key:

```bash
cp .env.example .env
```

Edit `.env`:

```bash
POLYGON_API_KEY=pk_your_key_here
```

The CLI loads `.env` automatically on startup via `python-dotenv`. Anything
in your shell environment wins over `.env`, and `.env` wins over
`config.yaml`.

## Verify the install

=== "CLI"

    ```bash
    poetry run oqe --help
    ```

    ```text
    usage: oqe [-h] {ask,themes} ...

    Options Query Engine - ask grounded questions about an options chain.

    positional arguments:
      {ask,themes}
        ask         Ask a single natural-language question.
        themes      List or preview the colour themes.

    options:
      -h, --help    show this help message and exit
    ```

=== "Python"

    ```python
    from oqe import __version__   # may not exist yet; safe to skip
    from oqe.agent import answer_question
    print(answer_question.__module__)   # 'oqe.agent'
    ```

=== "Tests"

    ```bash
    poetry run python -m pytest -q
    ```

    ```text
    .................................................. [ 31%]
    .................................................. [ 62%]
    .................................................. [ 93%]
    ............                                       [100%]
    169 passed in 0.32s
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
