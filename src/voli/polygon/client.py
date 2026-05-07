from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .http import PolygonHTTP


@dataclass(frozen=True)
class OptionChainQuery:
    contract_type: str | None = None  # "call" | "put"
    expiration_date: str | None = None  # "YYYY-MM-DD"
    strike_price: float | None = None
    sort: str | None = None  # e.g. "expiration_date" or "strike_price"
    order: str | None = None  # "asc" | "desc"
    limit: int = 250  # Polygon supports limit; keep modest for v1
    max_pages: int = 10  # safety valve


class PolygonClient:
    """
    Thin, testable wrapper around Polygon REST endpoints.
    Returns raw JSON dicts for now (model normalization comes next step).
    """

    def __init__(self, http: PolygonHTTP | None = None):
        self.http = http or PolygonHTTP()

    def close(self) -> None:
        self.http.close()

    # ---- Stocks ----
    def get_stock_snapshot(self, ticker: str) -> dict[str, Any]:
        # GET /v2/snapshot/locale/us/markets/stocks/tickers/{stocksTicker}
        return self.http.get_json(f"/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}")

    # ---- Options ----
    def get_option_contract_snapshot(self, underlying: str, option_contract: str) -> dict[str, Any]:
        # GET /v3/snapshot/options/{underlyingAsset}/{optionContract}
        return self.http.get_json(f"/v3/snapshot/options/{underlying}/{option_contract}")

    def get_option_chain_snapshot_page(
        self,
        underlying: str,
        q: OptionChainQuery,
        extra_params: dict[str, Any] | None = None,
        url_override: str | None = None,
    ) -> dict[str, Any]:
        # GET /v3/snapshot/options/{underlyingAsset}
        params: dict[str, Any] = {
            "limit": q.limit,
        }
        if q.contract_type:
            params["contract_type"] = q.contract_type
        if q.expiration_date:
            params["expiration_date"] = q.expiration_date
        if q.strike_price is not None:
            params["strike_price"] = q.strike_price
        if q.sort:
            params["sort"] = q.sort
        if q.order:
            params["order"] = q.order

        if extra_params:
            params.update(extra_params)

        path = url_override or f"/v3/snapshot/options/{underlying}"
        return self.http.get_json(path, params=params)

    def list_option_chain_snapshot(
        self,
        underlying: str,
        q: OptionChainQuery,
        extra_params: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """
        Returns: (first_page_json, all_results)
        Paginates via `next_url` when present.
        """
        first = self.get_option_chain_snapshot_page(underlying, q, extra_params=extra_params)
        results: list[dict[str, Any]] = list(first.get("results") or [])

        page = first
        pages = 1
        while pages < q.max_pages:
            next_url = page.get("next_url")
            if not next_url:
                break

            # Polygon often returns a full URL; httpx accepts absolute URLs even with a base_url client.
            page = self.get_option_chain_snapshot_page(
                underlying,
                q,
                extra_params=extra_params,
                url_override=next_url,
            )
            results.extend(list(page.get("results") or []))
            pages += 1

        return first, results
