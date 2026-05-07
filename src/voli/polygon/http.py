from __future__ import annotations

import json
import os
import random
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx


def _is_debug_enabled() -> bool:
    return os.getenv("POLYGON_HTTP_DEBUG", "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _mask(s: str, keep: int = 4) -> str:
    if not s:
        return s
    if len(s) <= keep:
        return "*" * len(s)
    return "*" * (len(s) - keep) + s[-keep:]


# ----------------------------
# Errors (small taxonomy)
# ----------------------------


class PolygonError(Exception):
    """Base error for all Polygon integration issues."""


class PolygonAuthError(PolygonError):
    """401/403 from Polygon."""


class PolygonRateLimitError(PolygonError):
    """429 from Polygon after retries exhausted."""


class PolygonNotFoundError(PolygonError):
    """404 from Polygon."""


class PolygonHTTPError(PolygonError):
    """Other non-2xx responses."""


class PolygonNetworkError(PolygonError):
    """Timeouts / connection errors."""


def _api_key_from_env() -> str:
    key = os.getenv("POLYGON_API_KEY")
    if not key:
        raise PolygonAuthError(
            "Missing POLYGON_API_KEY env var. Set it (or add to .env) before calling Polygon."
        )
    return key


@dataclass(frozen=True)
class PolygonHTTPConfig:
    base_url: str = "https://api.polygon.io"
    timeout_s: float = 15.0
    max_retries: int = 5
    backoff_base_s: float = 0.4
    backoff_cap_s: float = 8.0
    user_agent: str = "voli/0.1 (voli)"


class PolygonHTTP:
    """
    Lowest-level HTTP helper:
    - Injects apiKey
    - Retries 429 + transient 5xx with exponential backoff + jitter
    - Raises stable exception types
    """

    def __init__(self, api_key: str | None = None, config: PolygonHTTPConfig | None = None):
        self.api_key = api_key or _api_key_from_env()
        self.cfg = config or PolygonHTTPConfig()

        self._client = httpx.Client(
            base_url=self.cfg.base_url,
            timeout=self.cfg.timeout_s,
            headers={"User-Agent": self.cfg.user_agent},
        )

        self.debug = _is_debug_enabled()

    def close(self) -> None:
        self._client.close()

    def get_json(self, path: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return self._request_json("GET", path, params=params)

    def _request_json(
        self,
        method: str,
        path: str,
        params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        merged_params: dict[str, Any] = dict(params or {})
        merged_params["apiKey"] = self.api_key

        attempt = 0
        while True:
            attempt += 1
            try:
                req_url = path
                if path.startswith("/"):
                    req_url = f"{self.cfg.base_url.rstrip('/')}{path}"
                if self.debug:
                    safe_params = dict(merged_params)
                    if "apiKey" in safe_params:
                        safe_params["apiKey"] = _mask(str(safe_params["apiKey"]))
                    print(f"[polygon] -> {method} {req_url} params={safe_params}")
                resp = self._client.request(method, path, params=merged_params)

                if self.debug:
                    print(f"[polygon] <- {resp.status_code} {req_url}")
            except (httpx.TimeoutException, httpx.RequestError) as e:
                if attempt >= self.cfg.max_retries:
                    raise PolygonNetworkError(
                        f"Polygon network error after {attempt} attempts: {e}"
                    ) from e
                self._sleep_backoff(attempt)
                continue

            # 2xx OK
            if 200 <= resp.status_code < 300:
                # Polygon returns JSON; keep failure mode explicit.
                try:
                    return resp.json()
                except json.JSONDecodeError as e:
                    raise PolygonHTTPError(
                        f"Polygon returned non-JSON body (status {resp.status_code})."
                    ) from e

            # Auth
            if resp.status_code in (401, 403):
                raise PolygonAuthError(
                    f"Polygon auth error (status {resp.status_code}): {resp.text}"
                )

            # Not found
            if resp.status_code == 404:
                raise PolygonNotFoundError(f"Polygon not found: {path}")

            # Rate limit / transient server errors -> retry
            if resp.status_code == 429 or resp.status_code in (500, 502, 503, 504):
                if attempt >= self.cfg.max_retries:
                    if resp.status_code == 429:
                        raise PolygonRateLimitError(
                            f"Polygon rate limited (429) after {attempt} attempts."
                        )
                    raise PolygonHTTPError(
                        f"Polygon HTTP {resp.status_code} after {attempt} attempts: {resp.text}"
                    )

                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        time.sleep(float(retry_after))
                    except ValueError:
                        self._sleep_backoff(attempt)
                else:
                    self._sleep_backoff(attempt)
                continue

            # Other 4xx
            raise PolygonHTTPError(f"Polygon HTTP {resp.status_code}: {resp.text}")

    def _sleep_backoff(self, attempt: int) -> None:
        # exp backoff with jitter
        exp = min(self.cfg.backoff_cap_s, self.cfg.backoff_base_s * (2 ** (attempt - 1)))
        jitter = random.uniform(0.0, exp * 0.25)
        time.sleep(exp + jitter)
