"""DataProvider Protocol + registry.

Voli ships with a Polygon provider. To add another (yfinance, Tradier, IBKR,
ORATS, ...) implement four small methods returning Voli domain models, then
expose your class either by:

  * Calling ``voli.providers.register("myprov", MyProvider())`` from your code, or
  * Declaring a ``voli.data_providers`` entry point in your package's
    ``pyproject.toml``::

        [tool.poetry.plugins."voli.data_providers"]
        myprov = "your_pkg.module:MyProvider"

Pick the active provider at runtime via ``voli ask --data-provider myprov`` or
``VOLI_DATA_PROVIDER=myprov``. Default is ``polygon``.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import Protocol, runtime_checkable

from voli.models import OptionContract, OptionGreeks, OptionQuote


@runtime_checkable
class DataProvider(Protocol):
    """Minimum contract a data provider must satisfy.

    Implementations return Voli's domain models (see ``voli.models``) plus a
    list of warning codes. Voli core handles caching, run-trace logging, and
    the response envelope so adapter authors don't have to.

    The ``name`` attribute is stamped into ``ToolMeta.primary_source`` and the
    ``source`` field of returned domain models, so it shows up in the CLI's
    cache marker (e.g. ``[polygon]`` / ``[tradier]``).
    """

    name: str

    def fetch_underlying_snapshot(
        self, ticker: str, *, asof: datetime | None = None
    ) -> tuple[dict, list[str]]:
        """Return ``(snapshot_dict, warnings)``.

        ``snapshot_dict`` keys: ``ticker``, ``spot``, ``ts`` (ISO-8601 UTC
        string or None), ``source``. Voli wraps it into ``UnderlyingSnapshot``.
        """

    def fetch_option_contracts(
        self,
        ticker: str,
        *,
        right: str | None = None,
        expiry: date | None = None,
        strike_min: float | None = None,
        strike_max: float | None = None,
        limit: int = 500,
    ) -> tuple[list[OptionContract], list[str]]: ...

    def fetch_option_quotes(
        self,
        option_symbols: list[str],
        *,
        asof: datetime | None = None,
    ) -> tuple[dict[str, OptionQuote], list[str]]:
        """Return ``({symbol: OptionQuote}, warnings)``."""

    def fetch_option_greeks(
        self,
        option_symbols: list[str],
        *,
        asof: datetime | None = None,
        mode: str = "vendor_only",
    ) -> tuple[dict[str, OptionGreeks], list[str]]:
        """Return ``({symbol: OptionGreeks}, warnings)``."""

    def fetch_option_chain_bulk(
        self,
        ticker: str,
        *,
        right: str | None = None,
        expiry: str | None = None,
        max_pages: int = 20,
    ) -> tuple[list[OptionContract], dict[str, OptionQuote], dict[str, OptionGreeks]] | None:
        """Optional one-shot chain fetch used by the analytics layer.

        Return ``None`` if your vendor doesn't support a single-call chain
        pull; voli will fall back to per-symbol calls. Implementing this is
        the difference between sub-second and 30-second analytics latency on
        liquid names like SPY.
        """


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, DataProvider] = {}
_active_override: str | None = None
_entry_points_loaded = False


def register(name: str, provider: DataProvider) -> None:
    """Register a provider instance under ``name``. Last write wins."""

    _REGISTRY[name] = provider


def list_providers() -> list[str]:
    """Names of all currently registered providers (after entry-point discovery)."""

    _discover_entry_points()
    return sorted(_REGISTRY.keys())


def get(name: str) -> DataProvider:
    """Look up a provider by name. Triggers entry-point discovery on miss."""

    if name in _REGISTRY:
        return _REGISTRY[name]
    _discover_entry_points()
    if name in _REGISTRY:
        return _REGISTRY[name]
    available = ", ".join(list_providers()) or "(none)"
    raise KeyError(
        f"No data provider named '{name}'. Available: {available}. "
        "Install a provider package (e.g. pip install voli-tradier) or "
        "register one programmatically with voli.providers.register()."
    )


def set_active(name: str | None) -> None:
    """Pin the active provider for this process. Pass ``None`` to clear."""

    global _active_override
    _active_override = name


def active_name() -> str:
    """Active provider name, in priority order: process override -> env -> 'polygon'."""

    if _active_override:
        return _active_override
    return os.environ.get("VOLI_DATA_PROVIDER", "polygon")


def get_active() -> DataProvider:
    """Resolve the active provider. Convenience for tool callsites."""

    return get(active_name())


def _discover_entry_points() -> None:
    """Load any ``voli.data_providers`` entry points exposed by installed packages.

    Idempotent. A broken third-party provider is skipped rather than crashing
    voli, so a stale plugin can't take down the CLI.
    """

    global _entry_points_loaded
    if _entry_points_loaded:
        return
    _entry_points_loaded = True
    try:
        from importlib.metadata import entry_points
    except ImportError:  # pragma: no cover - py3.7 fallback, not relevant here
        return
    try:
        eps = entry_points(group="voli.data_providers")
    except TypeError:
        # Older importlib.metadata signature
        eps = entry_points().get("voli.data_providers", [])  # type: ignore[attr-defined]
    for ep in eps:
        if ep.name in _REGISTRY:
            continue
        try:
            obj = ep.load()
            provider = (
                obj() if callable(obj) and not hasattr(obj, "fetch_underlying_snapshot") else obj
            )
            _REGISTRY[ep.name] = provider
        except Exception:
            # Fail soft - a broken plugin shouldn't crash the host.
            continue


# ---------------------------------------------------------------------------
# Bundled providers
# ---------------------------------------------------------------------------
# Register the in-tree Polygon provider so it's always available without
# relying on entry-point discovery (which only fires for installed packages).
# The actual import sits at the bottom to avoid circular imports during
# package init.

from voli.providers.polygon import PolygonProvider as _PolygonProvider  # noqa: E402

register("polygon", _PolygonProvider())
