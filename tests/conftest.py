# tests/conftest.py
from __future__ import annotations

import contextlib
import os
from pathlib import Path


def _set_if_unset(name: str, value: str) -> None:
    # Don't override user-provided settings; only set defaults for test runs.
    os.environ.setdefault(name, value)


# Choose a repo-local cache path (safe to delete).
_REPO_ROOT = Path(__file__).resolve().parents[1]
_TEST_CACHE_PATH = _REPO_ROOT / ".pytest_voli_cache.sqlite"

# Common env var names projects use for cache pathing.
# If your cache layer uses one of these, this will force a clean cache for tests.
_set_if_unset("VOLI_CACHE_PATH", str(_TEST_CACHE_PATH))
_set_if_unset("VOLI_SQLITE_CACHE_PATH", str(_TEST_CACHE_PATH))
_set_if_unset("VOLI_CACHE_SQLITE_PATH", str(_TEST_CACHE_PATH))

# Optional "disable cache" flags (harmless if unused by your code).
_set_if_unset("VOLI_DISABLE_CACHE", "0")
_set_if_unset("VOLI_CACHE_DISABLED", "0")

# Ensure the test cache file starts clean each pytest invocation.
with contextlib.suppress(FileNotFoundError):
    _TEST_CACHE_PATH.unlink()
