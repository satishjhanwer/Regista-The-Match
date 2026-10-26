"""The recorded-run evaluation script."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path

from regista.agents.__main__ import record

ROOT = Path(__file__).resolve().parents[2]


def _eval_module():
    spec = importlib.util.spec_from_file_location("eval_run", ROOT / "backend" / "scripts" / "eval_run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_eval_of_a_template_run(sims, tmp_path, monkeypatch):
    monkeypatch.setenv("REGISTA_LLM_PROVIDER", "none")
    match, _ = sims[7]
    out = tmp_path / "renders.json"
    asyncio.run(record(match, out, ["analyst-en", "casual-es-slm"], 4, {"goal", "press_change"}))
    m = _eval_module().evaluate(out, ROOT / "data" / "RGS-2026-0001.json")
    assert m["audit_ok"] == m["renders"] > 0
    assert m["model_renders"] == 0 and m["sources"] == {"template": m["renders"]}
    assert m["claims_on_air"] == m["claims_citing_facts"] + m["colour_claims"]
    assert "| Renderings on air" in _eval_module().markdown(m)


def test_rule_grouping():
    rule_of = _eval_module().rule_of
    assert rule_of("claim 1: number 2 does not match any cited fact") == "number not in a cited fact"
    assert rule_of("claims [1] are not in the requested language (es)") == "wrong language or script"
    assert rule_of("headline is 92 characters; the limit is 80") == "too long for the overlay"
