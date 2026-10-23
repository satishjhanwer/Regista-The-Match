"""The replay CLI prints one line per insight plus a timing summary."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data" / "RGS-2026-0001.json"


def test_cli_prints_timeline(tmp_path):
    out_json = tmp_path / "insights.jsonl"
    res = subprocess.run(
        [sys.executable, "-m", "regista.detect", str(DATA), "--json", str(out_json)],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).resolve().parents[1],
    )
    lines = res.stdout.splitlines()
    timeline = lines[: lines.index("")]
    goals = [ln for ln in timeline if " goal " in ln]
    assert len(goals) == 3 and "38:" in goals[0] and "Vukovic" in goals[2]
    assert "p95" in lines[-1]
    assert len(out_json.read_text(encoding="utf-8").splitlines()) == len(timeline)
