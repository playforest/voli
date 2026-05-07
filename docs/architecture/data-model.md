# Data model

Pydantic models in `voli.models` define the canonical shape every tool
returns and every analytics function consumes. They're frozen, validated,
and `extra="forbid"` so an unexpected field is a loud error rather than
a silent drift.

## Domain models

### `UnderlyingSnapshot`

```python
class UnderlyingSnapshot(StrictModel):
    ticker: str                  # min length 1
    spot: float                  # > 0
    ts: datetime                 # must be timezone-aware (UTC)
    source: Literal["polygon", "cache", "synthetic"]
```

### `OptionContract`

```python
class OptionContract(StrictModel):
    option_symbol: str           # vendor symbol, e.g. O:NVDA260516C00100000
    underlying: str
    expiry: date
    strike: float                # > 0
    right: Literal["C", "P"]
    multiplier: int = 100
    currency: str | None = "USD"
    exercise_style: Literal["american", "european"] | None = None
```

### `OptionQuote`

```python
class OptionQuote(StrictModel):
    option_symbol: str
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    mid: float | None = None     # auto-computed from bid+ask if missing
    ts: datetime                 # UTC
    source: Literal["polygon", "cache", "synthetic"]
```

### `OptionGreeks`

```python
class OptionGreeks(StrictModel):
    option_symbol: str
    delta: float | None = None   # in [-1, 1]
    gamma: float | None = None   # >= 0 (vendor noise clamped at 1e-3)
    theta: float | None = None   # often negative
    vega:  float | None = None   # >= 0
    iv:    float | None = None   # decimal, e.g. 0.42
    ts: datetime
    source: Literal["polygon", "cache", "synthetic"]
    model: Literal["vendor", "black_scholes"] | None = None
```

## Tool I/O models

`voli.tool_schemas` defines `Pydantic` input/output models per tool:

| Input | Output |
| --- | --- |
| `GetUnderlyingSnapshotInput` | `GetUnderlyingSnapshotOutput` (.snapshot) |
| `ListOptionContractsInput` | `ListOptionContractsOutput` (.contracts) |
| `GetOptionQuotesInput` | `GetOptionQuotesOutput` (.quotes) |
| `GetOptionGreeksInput` | `GetOptionGreeksOutput` (.greeks) |

Every output carries a `meta: ToolMeta` with:

```python
class ToolMeta(StrictModel):
    tool: str
    generated_at: datetime              # when the response was produced (UTC)
    asof: datetime | None               # requested asof (or None for latest)
    primary_source: Literal["polygon", "cache", "synthetic"]
    warnings: list[str]                 # NO_RESULTS, STALE_DATA, ...
```

## Analytics protocols

`voli.analytics.protocols` defines duck-typed Protocols that the analytics
functions accept. This lets tests pass small dataclasses without inheriting
from the Pydantic models:

```python
@runtime_checkable
class OptionContractLike(Protocol):
    expiry: date | datetime | str
    strike: float
    right: str

@runtime_checkable
class OptionGreeksLike(Protocol):
    iv: float | None
    delta: float | None
    gamma: float | None
    theta: float | None
    vega: float | None

@runtime_checkable
class OptionQuoteLike(Protocol):
    bid: float | None
    ask: float | None
    last: float | None
```

## Why "strict" models?

`StrictModel` sets `extra="forbid"` and `frozen=True`:

- Unknown fields become a validation error rather than silently dropping.
  Catches schema drift in vendor responses early.
- Frozen instances can't be mutated; tools that thread the same object
  through layers can't have a downstream caller introduce state.

## Timestamp invariants

Every `ts` field is timezone-aware UTC. Naive timestamps raise.
`datetime.now(UTC)` is the canonical call inside the package; when reading
nanosecond timestamps from Polygon we go via
`voli.polygon.helpers.ns_to_utc_iso`.

## See also

- [Polygon tools](../python-api/tools.md) — how vendor responses become these models.
- [`voli.tool_schemas`](https://github.com/playforest/voli/blob/main/src/voli/tool_schemas.py) for the full I/O surface.
