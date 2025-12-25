from datetime import UTC, datetime

from oqe.models import UnderlyingSnapshot
from oqe.tool_schemas import GetOptionGreeksInput


def main() -> None:
    UnderlyingSnapshot(ticker="NVDA", spot=123.45, ts=datetime.now(UTC), source="polygon")
    GetOptionGreeksInput(option_symbols=["O:NVDA260116C00120000"])
    print("Part 2 smoke OK")


if __name__ == "__main__":
    main()
