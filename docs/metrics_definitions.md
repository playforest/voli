# Part 5 — Metrics definitions (v1)

This document defines the **exact**, deterministic rules used by `oqe.analytics`.

## Conventions

- **Right**: normalized to `call` or `put`.
  - Accepted inputs: `call`/`put`, `C`/`P`, `c`/`p`.
- **Expiry**: treated as a `date` (`YYYY-MM-DD`). If a timestamp is provided, we use its `.date()`.
- **Flags**: computations return `None` values when data is missing/invalid, and include one or more string flags.
  - The orchestrator can surface this as `PARTIAL_DATA`.

## Mid price

**Function:** `mid_price(bid, ask, last=None)`

Rule order:
1. If `bid` and `ask` are present, non-negative, and `ask >= bid`:
   - `mid = (bid + ask) / 2`
2. Else if `last` is present, non-negative:
   - `mid = last` (flag: `MID_FROM_LAST`)
3. Else if only `bid` is present, non-negative:
   - `mid = bid` (flag: `MID_FROM_BID_ONLY`)
4. Else if only `ask` is present, non-negative:
   - `mid = ask` (flag: `MID_FROM_ASK_ONLY`)
5. Else:
   - `mid = None` (flag: `MID_MISSING`)

Whenever we do **not** use bid/ask midpoint, we also add `MID_NOT_FROM_BIDASK`.

## Relative spread

**Function:** `relative_spread(bid, ask)`

- `mid = (bid + ask) / 2`
- `relative_spread = (ask - bid) / mid`

Returns `None` if:
- `bid` or `ask` missing
- negative quotes
- `ask < bid`
- `mid == 0`

## Spread-too-wide filter

**Function:** `is_spread_too_wide(bid, ask, max_relative_spread=0.20)`

- Computes `relative_spread`.
- Returns `True` if `relative_spread > max_relative_spread`.
- Returns `None` with flags if spread cannot be computed.

## ATM strike selection

**Function:** `select_atm_strike(spot, strikes)`

- Choose the strike `K` minimizing `abs(K - spot)`.
- **Deterministic tie-break:** if two strikes are equally close, choose the **lower** strike.
- Returns `None` if `strikes` is empty.

## Term structure comparison

**Function:** `atm_iv_term_structure(spot, contracts, greeks_by_symbol, right='call')`

Goal: compare **ATM IV** for the **front** expiry vs the **next** expiry using the **same strike**.

Algorithm:
1. Filter to contracts matching `right`.
2. Identify the two earliest expiries: `front`, `next`.
3. Build the strike grid for `front` and choose `atm_strike` using `select_atm_strike(spot, strikes_front)`.
4. For each of `front` and `next`:
   - select the contract with `strike == atm_strike` (deterministic ordering by option symbol)
   - look up `iv` from `greeks_by_symbol[option_symbol].iv`

Missing or absent `iv` yields `None` and flags like `MISSING_GREEKS`, `MISSING_IV`, `CONTRACT_NOT_FOUND`.

## Skew curve

**Function:** `strike_iv_pairs(contracts, greeks_by_symbol, expiry, right)`

- For the given `expiry` and `right`, return sorted `(strike, iv)` pairs.
- Contracts with missing greeks or missing `iv` are **skipped** and flagged.
- Duplicate strikes are deduplicated deterministically (first seen by strike+symbol ordering), flagged `DUPLICATE_STRIKE`.

## Skew slope

**Function:** `skew_slope_ols(pairs)`

- Computes OLS slope for `iv ~ strike`:
  - `slope = cov(strike, iv) / var(strike)`
- Returns `None` if fewer than 2 points or if all strikes are identical.

