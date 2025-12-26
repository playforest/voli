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
