from __future__ import annotations

from typing import Any

from oqe.models import OptionContract


def option_contract_from_snapshot_row(
    row: dict[str, Any],
    *,
    fallback_underlying: str | None = None,
) -> OptionContract:
    d = row.get("details") or {}

    option_symbol = d["ticker"]
    expiry = d["expiration_date"]
    strike = float(d["strike_price"])

    ct = (d.get("contract_type") or "").lower()
    right = "C" if ct == "call" else "P" if ct == "put" else ct

    ua = row.get("underlying_asset") or {}
    underlying = ua.get("ticker") or fallback_underlying
    if not underlying:
        raise ValueError(
            "Missing underlying ticker (row.underlying_asset.ticker and fallback_underlying are both empty)"
        )

    multiplier = int(d.get("shares_per_contract", 100))

    return OptionContract(
        option_symbol=option_symbol,
        underlying=underlying,
        expiry=expiry,
        strike=strike,
        right=right,
        multiplier=multiplier,
    )
