"""yfinance-backed implementation of :class:`voli.providers.DataProvider`.

This is a **reference adapter** — read it end-to-end alongside the bundled
``voli.providers.polygon`` to see how the same Protocol gets implemented
against two very different vendors.

Caveats with yfinance specifically:

  * Free + no API key, but rate-limited and community-maintained — the
    underlying scraper occasionally breaks when Yahoo changes their site.
  * Only ``impliedVolatility`` is published; vendor delta/gamma/theta/vega
    are not available, so the greeks fetcher returns those fields as
    ``None`` and warns ``PARTIAL_DATA``.
  * Asof / historical replay is not supported (the snapshot endpoint is
    latest-only). When ``asof`` is set we still return the latest snapshot
    and warn ``VENDOR_LIMIT``.

The shape of voli option symbols is preserved: yfinance gives raw OCC
strings like ``NVDA260516C00100000``; voli convention is the
``O:NVDA260516C00100000`` form (matching Polygon). We translate at the
provider boundary so downstream code never has to care which vendor
served the data.
"""

from __future__ import annotations

import contextlib
import re
from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Any

import yfinance as yf

from voli.models import OptionContract, OptionGreeks, OptionQuote

# OCC option symbol: TICKER + YYMMDD + C/P + STRIKE*1000 (8 digits)
# Optional ``O:`` prefix matches Voli's bundled Polygon convention.
_OCC_RE = re.compile(r"^(?:O:)?([A-Z.]+)(\d{2})(\d{2})(\d{2})([CP])(\d{8})$")


def _to_voli_symbol(yf_sym: str) -> str:
    return yf_sym if yf_sym.startswith("O:") else f"O:{yf_sym}"


def _to_yf_symbol(voli_sym: str) -> str:
    return voli_sym[2:] if voli_sym.startswith("O:") else voli_sym


def _parse_occ(sym: str) -> tuple[str, date, str, float]:
    """Return ``(underlying, expiry, right, strike)`` from an OCC symbol."""

    m = _OCC_RE.match(sym)
    if not m:
        raise ValueError(f"Cannot parse OCC option symbol: {sym}")
    underlying, yy, mm, dd, right, strike_raw = m.groups()
    expiry = date(2000 + int(yy), int(mm), int(dd))
    strike = int(strike_raw) / 1000.0
    return underlying, expiry, right, strike


def _utc_ts(value: Any) -> datetime:
    """Coerce a yfinance / pandas Timestamp to a UTC tz-aware datetime."""

    if value is None:
        return datetime.now(UTC)
    if hasattr(value, "to_pydatetime"):
        d = value.to_pydatetime()
    elif isinstance(value, datetime):
        d = value
    else:
        return datetime.now(UTC)
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)
    return d.astimezone(UTC)


def _safe_float(value: Any) -> float | None:
    """Coerce yfinance numerics to float, returning None for NaN / None."""

    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def _concat_chain(chain) -> Any:
    """Concatenate calls + puts into a single DataFrame."""

    import pandas as pd

    return pd.concat([chain.calls, chain.puts], ignore_index=True)


class YFinanceProvider:
    """DataProvider implementation backed by Yahoo Finance via ``yfinance``."""

    name: str = "yfinance"

    # ------------------------------------------------------------------ snapshot
    def fetch_underlying_snapshot(
        self, ticker: str, *, asof: datetime | None = None
    ) -> tuple[dict, list[str]]:
        warnings: list[str] = []
        if asof is not None:
            warnings.append("VENDOR_LIMIT")

        t = yf.Ticker(ticker)
        spot: float | None = None
        ts = datetime.now(UTC)

        # fast_info is the cheapest spot lookup; falls back to recent history.
        try:
            fast = t.fast_info
            spot = _safe_float(fast.get("lastPrice") or fast.get("last_price"))
        except Exception:  # noqa: BLE001 - yfinance raises a zoo of types
            spot = None

        if spot is None:
            try:
                hist = t.history(period="1d")
                if not hist.empty:
                    spot = _safe_float(hist["Close"].iloc[-1])
                    ts = _utc_ts(hist.index[-1])
            except Exception:  # noqa: BLE001
                pass

        if spot is None or spot <= 0:
            warnings.append("NO_RESULTS")
            raise RuntimeError(f"yfinance: no spot price available for {ticker!r}")

        return (
            {
                "ticker": ticker,
                "spot": float(spot),
                "ts": ts.isoformat().replace("+00:00", "Z"),
                "source": self.name,
            },
            warnings,
        )

    # ----------------------------------------------------------------- contracts
    def fetch_option_contracts(
        self,
        ticker: str,
        *,
        right: str | None = None,
        expiry: date | None = None,
        strike_min: float | None = None,
        strike_max: float | None = None,
        limit: int = 500,
    ) -> tuple[list[OptionContract], list[str]]:
        warnings: list[str] = []
        t = yf.Ticker(ticker)

        try:
            all_expiries = list(t.options or [])
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"yfinance: failed to list expiries for {ticker!r}: {exc}") from exc

        if expiry is not None:
            target = expiry.isoformat()
            if target not in all_expiries:
                warnings.append("NO_RESULTS")
                return [], warnings
            expiries_to_fetch = [target]
        else:
            expiries_to_fetch = all_expiries

        contracts: list[OptionContract] = []
        for exp_str in expiries_to_fetch:
            if len(contracts) >= limit:
                break
            try:
                chain = t.option_chain(exp_str)
            except Exception:  # noqa: BLE001
                continue

            for df, side in [(chain.calls, "C"), (chain.puts, "P")]:
                if right and side != right:
                    continue
                for _, row in df.iterrows():
                    if len(contracts) >= limit:
                        break
                    strike = _safe_float(row.get("strike"))
                    if strike is None or strike <= 0:
                        continue
                    if strike_min is not None and strike < strike_min:
                        continue
                    if strike_max is not None and strike > strike_max:
                        continue
                    yf_sym = row.get("contractSymbol")
                    if not isinstance(yf_sym, str):
                        continue
                    try:
                        contracts.append(
                            OptionContract(
                                option_symbol=_to_voli_symbol(yf_sym),
                                underlying=ticker,
                                expiry=date.fromisoformat(exp_str),
                                strike=strike,
                                right=side,
                                multiplier=100,
                                currency=str(row.get("currency") or "USD"),
                            )
                        )
                    except Exception:  # noqa: BLE001 - pydantic validation, etc.
                        continue

        if not contracts:
            warnings.append("NO_RESULTS")

        return contracts, warnings

    # -------------------------------------------------------------------- quotes
    def fetch_option_quotes(
        self,
        option_symbols: list[str],
        *,
        asof: datetime | None = None,
    ) -> tuple[dict[str, OptionQuote], list[str]]:
        warnings: list[str] = []
        if asof is not None:
            warnings.append("VENDOR_LIMIT")

        partial = False
        out: dict[str, OptionQuote] = {}

        # Group requested symbols by (underlying, expiry) so each chain is fetched
        # once even when multiple strikes / rights share the same chain page.
        groups: dict[tuple[str, str], list[str]] = defaultdict(list)
        for voli_sym in option_symbols:
            try:
                underlying, exp, _r, _k = _parse_occ(voli_sym)
                groups[(underlying, exp.isoformat())].append(voli_sym)
            except ValueError:
                partial = True

        for (underlying, exp_str), syms in groups.items():
            try:
                chain = yf.Ticker(underlying).option_chain(exp_str)
            except Exception:  # noqa: BLE001
                partial = True
                continue
            df = _concat_chain(chain)
            sym_set = {_to_yf_symbol(s) for s in syms}
            for _, row in df.iterrows():
                yf_sym = row.get("contractSymbol")
                if not isinstance(yf_sym, str) or yf_sym not in sym_set:
                    continue
                voli_sym = _to_voli_symbol(yf_sym)
                bid = _safe_float(row.get("bid"))
                ask = _safe_float(row.get("ask"))
                # Compute mid here. Voli's OptionQuote auto-computes via a
                # model_validator but that pattern emits a UserWarning under
                # pydantic >= 2.10; pre-computing avoids it entirely.
                mid = (bid + ask) / 2.0 if bid is not None and ask is not None else None
                try:
                    out[voli_sym] = OptionQuote(
                        option_symbol=voli_sym,
                        bid=bid,
                        ask=ask,
                        last=_safe_float(row.get("lastPrice")),
                        mid=mid,
                        ts=_utc_ts(row.get("lastTradeDate")),
                        source=self.name,
                    )
                except Exception:  # noqa: BLE001
                    partial = True

        if partial:
            warnings.append("PARTIAL_DATA")
        if not out:
            warnings.append("NO_RESULTS")
        return out, warnings

    # -------------------------------------------------------------------- greeks
    def fetch_option_greeks(
        self,
        option_symbols: list[str],
        *,
        asof: datetime | None = None,
        mode: str = "vendor_only",
    ) -> tuple[dict[str, OptionGreeks], list[str]]:
        # yfinance only publishes IV. Voli convention: still return entries
        # so the caller can use IV for term structure / skew, but flag
        # PARTIAL_DATA so the writer knows delta/gamma/theta/vega are absent.
        warnings: list[str] = ["PARTIAL_DATA"]
        if asof is not None:
            warnings.append("VENDOR_LIMIT")

        out: dict[str, OptionGreeks] = {}
        groups: dict[tuple[str, str], list[str]] = defaultdict(list)
        for voli_sym in option_symbols:
            try:
                underlying, exp, _r, _k = _parse_occ(voli_sym)
                groups[(underlying, exp.isoformat())].append(voli_sym)
            except ValueError:
                continue

        for (underlying, exp_str), syms in groups.items():
            try:
                chain = yf.Ticker(underlying).option_chain(exp_str)
            except Exception:  # noqa: BLE001
                continue
            df = _concat_chain(chain)
            sym_set = {_to_yf_symbol(s) for s in syms}
            for _, row in df.iterrows():
                yf_sym = row.get("contractSymbol")
                if not isinstance(yf_sym, str) or yf_sym not in sym_set:
                    continue
                voli_sym = _to_voli_symbol(yf_sym)
                iv = _safe_float(row.get("impliedVolatility"))
                try:
                    out[voli_sym] = OptionGreeks(
                        option_symbol=voli_sym,
                        delta=None,
                        gamma=None,
                        theta=None,
                        vega=None,
                        iv=iv if iv and iv > 0 else None,
                        ts=_utc_ts(row.get("lastTradeDate")),
                        source=self.name,
                        model="vendor",
                    )
                except Exception:  # noqa: BLE001
                    continue

        if not out:
            warnings.append("NO_RESULTS")
        return out, warnings

    # ---------------------------------------------------------------- bulk chain
    def fetch_option_chain_bulk(
        self,
        ticker: str,
        *,
        right: str | None = None,
        expiry: str | None = None,
        max_pages: int = 20,
    ) -> tuple[list[OptionContract], dict[str, OptionQuote], dict[str, OptionGreeks]]:
        """Single-pass chain fetch — keeps analytics latency reasonable.

        yfinance still costs one HTTP call per expiry (the API doesn't have
        a cross-expiry chain endpoint). The win vs. the per-symbol fallback
        is not having to issue separate calls for quotes and greeks since
        both come from the same DataFrame.
        """

        t = yf.Ticker(ticker)
        try:
            all_expiries = list(t.options or [])
        except Exception:  # noqa: BLE001
            return [], {}, {}

        if expiry:
            expiries_to_fetch = [expiry] if expiry in all_expiries else []
        else:
            expiries_to_fetch = all_expiries[:max_pages]

        contracts: list[OptionContract] = []
        quotes: dict[str, OptionQuote] = {}
        greeks: dict[str, OptionGreeks] = {}

        for exp_str in expiries_to_fetch:
            try:
                chain = t.option_chain(exp_str)
            except Exception:  # noqa: BLE001
                continue
            for df, side in [(chain.calls, "C"), (chain.puts, "P")]:
                if right and side != right:
                    continue
                for _, row in df.iterrows():
                    yf_sym = row.get("contractSymbol")
                    if not isinstance(yf_sym, str):
                        continue
                    voli_sym = _to_voli_symbol(yf_sym)
                    strike = _safe_float(row.get("strike"))
                    if strike is None or strike <= 0:
                        continue
                    try:
                        contracts.append(
                            OptionContract(
                                option_symbol=voli_sym,
                                underlying=ticker,
                                expiry=date.fromisoformat(exp_str),
                                strike=strike,
                                right=side,
                            )
                        )
                    except Exception:  # noqa: BLE001
                        continue
                    ts = _utc_ts(row.get("lastTradeDate"))
                    bid = _safe_float(row.get("bid"))
                    ask = _safe_float(row.get("ask"))
                    mid = (bid + ask) / 2.0 if bid is not None and ask is not None else None
                    with contextlib.suppress(Exception):
                        quotes[voli_sym] = OptionQuote(
                            option_symbol=voli_sym,
                            bid=bid,
                            ask=ask,
                            last=_safe_float(row.get("lastPrice")),
                            mid=mid,
                            ts=ts,
                            source=self.name,
                        )
                    iv = _safe_float(row.get("impliedVolatility"))
                    with contextlib.suppress(Exception):
                        greeks[voli_sym] = OptionGreeks(
                            option_symbol=voli_sym,
                            iv=iv if iv and iv > 0 else None,
                            ts=ts,
                            source=self.name,
                            model="vendor",
                        )

        return contracts, quotes, greeks
