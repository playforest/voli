# Releasing

There's no published release yet — OQE is at the "main branch is canonical"
stage. This page captures the intended flow for when that changes.

## Versioning

[Semantic versioning](https://semver.org/) once we tag `0.1.0`:

| Bump | When |
| --- | --- |
| Patch (`0.1.x`) | Bug fixes, doc-only updates, internal refactors. |
| Minor (`0.x.0`) | New features that don't break existing CLI flags or Python signatures. |
| Major (`1.x.0`) | Breaking changes (renamed flags, removed Python APIs, JSON schema changes). |

## Pre-flight checklist

Before tagging:

```bash
poetry run ruff check .
poetry run ruff format .
poetry run python -m pytest -q
poetry run python eval/run_eval.py --json | jq '.failed'   # must be 0
poetry run mkdocs build                                    # must produce no warnings
```

If all four are clean, you're good.

## Tagging

```bash
# Bump version in pyproject.toml
poetry version patch     # or minor / major

# Commit + tag
git add pyproject.toml
git commit -m "release: vX.Y.Z"
git tag -a vX.Y.Z -m "release: vX.Y.Z"
git push origin main vX.Y.Z
```

## Changelog

Maintain `CHANGELOG.md` (Keep a Changelog format):

```md
## [0.2.0] - 2026-06-15
### Added
- ...

### Changed
- ...

### Fixed
- ...
```

Reference issue / PR numbers where relevant.

## Publishing (if/when)

If we publish to PyPI later:

```bash
poetry build
poetry publish        # uses PYPI_TOKEN env var
```

Until then, `pip install git+https://github.com/playforest/options-query-agent@vX.Y.Z`
works for downstream users.

## Docs deploy (deferred)

The MkDocs site builds locally. GitHub Pages auto-deploy is intentionally
deferred — when you want it, add `.github/workflows/docs.yml` with
`mkdocs gh-deploy --force` on push to `main`.

## Hotfix flow

If a regression ships:

1. Add an eval case that captures the broken behaviour first
   (`eval/prompts.jsonl`).
2. Verify the harness fails on it.
3. Fix the code.
4. Verify the harness passes.
5. Patch-bump and tag.

This keeps the eval dataset growing alongside the bug history.
