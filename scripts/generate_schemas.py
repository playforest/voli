# scripts/generate_schemas.py
from __future__ import annotations

import json
from pathlib import Path

from voli import tool_schemas as ts

OUT = Path("schemas/tools.v1.json")


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "version": "v1",
        "tools": {
            "get_underlying_snapshot": {
                "input_schema": ts.GetUnderlyingSnapshotInput.model_json_schema(),
                "output_schema": ts.GetUnderlyingSnapshotOutput.model_json_schema(),
            },
            "list_option_contracts": {
                "input_schema": ts.ListOptionContractsInput.model_json_schema(),
                "output_schema": ts.ListOptionContractsOutput.model_json_schema(),
            },
            "get_option_quotes": {
                "input_schema": ts.GetOptionQuotesInput.model_json_schema(),
                "output_schema": ts.GetOptionQuotesOutput.model_json_schema(),
            },
            "get_option_greeks": {
                "input_schema": ts.GetOptionGreeksInput.model_json_schema(),
                "output_schema": ts.GetOptionGreeksOutput.model_json_schema(),
            },
            "get_option_oi": {
                "input_schema": ts.GetOptionOIInput.model_json_schema(),
                "output_schema": ts.GetOptionOIOutput.model_json_schema(),
            },
        },
    }

    OUT.write_text(json.dumps(payload, indent=2, sort_keys=True))
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
