"""Contract drift guard: committed JSON Schemas must match the Pydantic models.

If this fails, run `python scripts/export_schemas.py` and `npm run contracts`
in /frontend, then commit both.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _exporter():
    spec = importlib.util.spec_from_file_location("export_schemas", ROOT / "backend" / "scripts" / "export_schemas.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_committed_schemas_match_models():
    mod = _exporter()
    for name, model in mod.SCHEMAS.items():
        expected = mod.strip_property_titles(model.model_json_schema(mode="serialization"))
        committed = json.loads((ROOT / "contracts" / "schema" / f"{name}.schema.json").read_text(encoding="utf-8"))
        assert committed == expected, f"{name}.schema.json is stale"


def test_discriminator_is_required_in_every_event():
    schema = json.loads((ROOT / "contracts" / "schema" / "match-file.schema.json").read_text(encoding="utf-8"))
    for name, definition in schema["$defs"].items():
        if name.endswith("Event"):
            assert "type" in definition["required"], name
