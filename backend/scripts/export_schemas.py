"""Export JSON Schemas for the event and overlay contracts.

The frontend generates its TypeScript types from these files
(`npm run contracts` in /frontend), so Python stays the single source of truth.

    python scripts/export_schemas.py
"""

from __future__ import annotations

import json
from pathlib import Path

from regista.contracts.events import GroundTruth, MatchFile
from regista.contracts.insight import FanProfile, OverlayPayload
from regista.contracts.stream import StreamContract

OUT = Path(__file__).resolve().parents[2] / "contracts" / "schema"

SCHEMAS = {
    "match-file": MatchFile,
    "ground-truth": GroundTruth,
    "overlay-payload": OverlayPayload,
    "fan-profile": FanProfile,
    "stream": StreamContract,
}


def strip_property_titles(node):
    """Drop per-property titles so the TS generator emits inline types, not one alias per field."""
    if isinstance(node, dict):
        for prop in node.get("properties", {}).values():
            if isinstance(prop, dict):
                prop.pop("title", None)
        for value in node.values():
            strip_property_titles(value)
    elif isinstance(node, list):
        for item in node:
            strip_property_titles(item)
    return node


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, model in SCHEMAS.items():
        schema = strip_property_titles(model.model_json_schema(mode="serialization"))
        (OUT / f"{name}.schema.json").write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {name}.schema.json")


if __name__ == "__main__":
    main()
