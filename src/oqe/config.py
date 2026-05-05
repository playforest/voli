"""Optional YAML config loader.

Existing modules read settings from OQE_* env vars (cache path, trace dir,
default theme, ...). This module lets users supply those same values via a
`config.yaml` file without changing any consumer.

Precedence (highest wins):
  1. Process env vars set BEFORE the config loader runs.
  2. Values from the YAML config file.
  3. Built-in defaults (each consumer module already provides one).

The loader exports values into `os.environ` so consumers - which already
key off env vars - need no changes. Calling `load_config()` more than once
is a no-op for keys already set.

Lookup order for the config file:
  1. `$OQE_CONFIG` if set
  2. `./config.yaml` (CWD)
  3. `~/.oqe/config.yaml`

Each is checked in order; the first existing file wins. If none exist,
nothing is loaded and the function silently returns.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# YAML is optional - if pyyaml isn't installed (very lean install), config
# loading degrades to env-only without error.
try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - exercised only when yaml is missing
    yaml = None  # type: ignore


# Map from config-file key -> env-var name. Anything outside this map is
# ignored so a typo in config.yaml doesn't silently leak into the process.
_KEY_TO_ENV: dict[str, str] = {
    "cache_path": "OQE_CACHE_PATH",
    "trace_dir": "OQE_TRACE_DIR",
    "default_theme": "OQE_THEME",
    "theme_cursor_path": "OQE_THEME_CURSOR",
    "log_level": "OQE_LOG_LEVEL",
    "log_format": "OQE_LOG_FORMAT",
    "polygon_api_key": "POLYGON_API_KEY",
    "polygon_http_debug": "POLYGON_HTTP_DEBUG",
}


@dataclass(frozen=True)
class OQEConfig:
    """Resolved config snapshot. Most callers don't need this; the env-var
    side effect of `load_config()` is the primary contract.
    """

    source_path: Path | None
    values: dict[str, str] = field(default_factory=dict)

    def get(self, key: str, default: str | None = None) -> str | None:
        return self.values.get(key, default)


def _candidate_paths() -> list[Path]:
    out: list[Path] = []
    env = os.environ.get("OQE_CONFIG")
    if env:
        out.append(Path(env).expanduser())
    out.append(Path("config.yaml"))
    out.append(Path("~/.oqe/config.yaml").expanduser())
    return out


def _read_yaml(path: Path) -> dict[str, Any]:
    if yaml is None:
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    parsed = yaml.safe_load(text) or {}
    if not isinstance(parsed, dict):
        raise ValueError(f"{path}: top-level YAML must be a mapping, got {type(parsed).__name__}")
    return parsed


def load_config(*, override_env: bool = False) -> OQEConfig:
    """Load the first existing config file and export its values to env vars.

    `override_env=False` (default) means an env var already set wins over the
    config file - useful so a CI job can always force a setting via env.
    Pass `override_env=True` if the YAML file should be authoritative.
    """

    for candidate in _candidate_paths():
        if not candidate.is_file():
            continue
        raw = _read_yaml(candidate)
        applied: dict[str, str] = {}
        for key, val in raw.items():
            env_name = _KEY_TO_ENV.get(key)
            if env_name is None:
                continue  # silently ignore unknown keys
            if not override_env and env_name in os.environ:
                continue
            os.environ[env_name] = str(val)
            applied[key] = str(val)
        return OQEConfig(source_path=candidate, values=applied)

    return OQEConfig(source_path=None, values={})


def known_keys() -> tuple[str, ...]:
    """Public list of accepted config keys (used by docs + sanity checks)."""

    return tuple(_KEY_TO_ENV.keys())
