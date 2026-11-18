"""Truth score: random plans are well formed, the demo plan is untouched, and the detectors keep a floor on unseen plants."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from regista.sim.director import SCRIPT, WINDOWS, Plan
from regista.sim.engine import simulate
from regista.sim.plans import random_plan

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def ts():
    spec = importlib.util.spec_from_file_location("truth_score", ROOT / "backend" / "scripts" / "truth_score.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["truth_score"] = mod  # its dataclasses look themselves up there
    spec.loader.exec_module(mod)
    return mod


def test_random_plans_are_well_formed():
    plans = [random_plan(seed) for seed in range(200)]
    assert plans == [random_plan(seed) for seed in range(200)]  # deterministic
    controls = sum(not p.windows for p in plans)
    assert 30 <= controls <= 70  # about one in four
    for p in plans:
        assert p.script == ()
        assert len({w.mechanism for w in p.windows}) == len(p.windows) <= 2
        for w in p.windows:
            base = 0.0 if w.start_min < 45 else 45.0
            assert base + 5 <= w.start_min < w.end_min <= base + 44  # inside one half
            assert 10 <= w.end_min - w.start_min <= 15
            assert (w.team_id is None) == (w.mechanism == "chaos")
        for a, b in zip(p.windows, p.windows[1:], strict=False):
            assert b.start_min >= a.end_min + 5
    kinds = {(w.mechanism, w.difficulty) for p in plans for w in p.windows}
    assert len(kinds) == 6


def test_the_demo_plan_is_the_default(sims):
    match, truth = sims[7]
    again, _ = simulate(seed=7, plan=Plan(windows=tuple(WINDOWS), script=tuple(SCRIPT)))
    assert again.model_dump_json() == match.model_dump_json()
    assert [s.mechanism for s in truth.storylines] == ["control", "chaos", "press", "go_long"]
    assert [s.team_id for s in truth.storylines] == ["NVL", None, "SLM", "NVL"]


def test_the_demo_storylines_are_found_on_the_right_side(ts, sims):
    from regista.detect import run_match

    match, truth = sims[7]
    insights, _ = run_match(match)
    score = ts.score_match(7, truth, insights)
    assert [p.storyline.storyline_id for p in score.plants] == ["S1_home_control", "S2_chaos_spell", "S3_away_press_shift"]
    assert all(p.delay_min is not None and 0 <= p.delay_min < 6 and p.right_side for p in score.plants)


def test_floor_on_unseen_plants(ts):
    """A regression floor on 16 fresh seeds, set below today's numbers (docs/DECISIONS.md D36): not a target."""
    summary = ts.summarize(ts.run(list(range(101, 117))))
    rows = summary["rows"]
    assert summary["controls"] >= 2
    assert rows["all"]["recall"] >= 0.5, rows["all"]
    assert rows["all"]["right_side"] >= 0.9, rows["all"]
    assert rows["all"]["median_min"] <= 5.0, rows["all"]
    assert summary["false_alarms_by_mechanism"]["press"] <= 1.5, summary["false_alarms_by_mechanism"]
    text = ts.render(summary, markdown=True)
    assert text.startswith("16 matches") and "| press (strong) |" in text
