"""Lightweight structured logging.

Two formats, picked by `OQE_LOG_FORMAT` (or config.yaml `log_format`):
  * `text` (default) - one line per record, themed when stderr is a TTY,
    plain when redirected. Easy for humans.
  * `json` - one JSON object per record, no colour. Easy for machines / log
    aggregators / CI.

Level via `OQE_LOG_LEVEL` (default `WARNING`). The CLI calls `setup_logging()`
once at startup; library users who import oqe.* get no implicit logging
config (we don't add handlers to the root logger they didn't ask for).
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime

from .cli_render import THEMES, make_theme

_DEFAULT_LEVEL = "WARNING"
_DEFAULT_FORMAT = "text"

_LEVELS: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def _level_from_env() -> int:
    name = os.environ.get("OQE_LOG_LEVEL", _DEFAULT_LEVEL).upper()
    return _LEVELS.get(name, logging.WARNING)


def _format_from_env() -> str:
    return os.environ.get("OQE_LOG_FORMAT", _DEFAULT_FORMAT).lower()


def _stderr_is_tty() -> bool:
    try:
        return os.isatty(sys.stderr.fileno())
    except (OSError, ValueError, AttributeError):
        return False


class _ThemedTextFormatter(logging.Formatter):
    """Single-line themed text format.

    Uses the active CLI theme so log lines feel visually consistent with the
    command output. Falls back to plain text when stderr isn't a TTY.
    """

    LEVEL_KEY = {
        logging.DEBUG: "dim",
        logging.INFO: "value",
        logging.WARNING: "warn",
        logging.ERROR: "warn",
        logging.CRITICAL: "warn",
    }

    def __init__(self, *, color: bool, theme_name: str | None = None) -> None:
        super().__init__()
        self.color = color
        self.theme_name = theme_name

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        level = record.levelname
        msg = record.getMessage()
        if not self.color:
            return f"{ts} [{level}] {record.name}: {msg}"

        t = make_theme(True, theme=self.theme_name)
        level_styler = getattr(t, self.LEVEL_KEY.get(record.levelno, "value"))
        return f"{t.dim(ts)} [{level_styler(level)}] {t.label(record.name)}: {t.value(msg)}"


class _JSONFormatter(logging.Formatter):
    """One JSON object per record. Stable key order so log diffs read clean."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def setup_logging(
    *,
    level: int | str | None = None,
    fmt: str | None = None,
    theme_name: str | None = None,
) -> logging.Logger:
    """Configure the `oqe` logger and return it.

    Idempotent: replaces any handlers the previous call attached so reruns
    don't double-log.
    """

    fmt = (fmt or _format_from_env() or _DEFAULT_FORMAT).lower()
    if isinstance(level, str):
        level = _LEVELS.get(level.upper(), logging.WARNING)
    if level is None:
        level = _level_from_env()

    if theme_name is None:
        theme_name = os.environ.get("OQE_THEME") or "bloomberg"
    if theme_name not in THEMES:
        theme_name = "bloomberg"

    handler = logging.StreamHandler(sys.stderr)
    if fmt == "json":
        handler.setFormatter(_JSONFormatter())
    else:
        handler.setFormatter(_ThemedTextFormatter(color=_stderr_is_tty(), theme_name=theme_name))

    logger = logging.getLogger("oqe")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger


def get_logger(name: str = "oqe") -> logging.Logger:
    """Return a child logger of the `oqe` namespace.

    Example:
        from oqe.logging import get_logger
        log = get_logger("oqe.eval")
        log.info("starting eval ...")
    """

    if not name.startswith("oqe"):
        name = f"oqe.{name}"
    return logging.getLogger(name)
