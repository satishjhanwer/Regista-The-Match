"""Acceptance tests for the hot path: planted storylines and scripted moments become Insights.

Run on seeds 1-5 and 7. Ground truth is read here (tests only) to locate the scripted events.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from regista.contracts.events import match_minute
from regista.detect import run_match

SEEDS = [1, 2, 3, 4, 5, 7]
SCRIPTED_SCORER = {"G1": "NVL-09", "G2": "SLM-09", "G3": "NVL-09"}


@pytest.fixture(scope="module")
def runs(sims):
    return {seed: run_match(sims[seed][0]) for seed in SEEDS}


def minute(ins) -> float:
    return match_minute(ins.clock.period, ins.clock.t)


def near(ins, ev, seconds: float = 5.0) -> bool:
    return ins.clock.period == ev.period and 0.0 <= ins.clock.t - ev.t <= seconds


def facts_by_key(ins) -> dict:
    return {f.key: f for f in ins.facts}


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("moment", ["G1", "G2", "G3"])
def test_scripted_goal_produces_goal_insight(sims, runs, seed, moment):
    match, truth = sims[seed]
    insights, _ = runs[seed]
    ev = next(e for e in match.events if e.event_id == truth.scripted_event_ids[moment])
    goals = [i for i in insights if i.kind == "goal" and near(i, ev)]
    assert len(goals) == 1
    g = goals[0]
    scorer = SCRIPTED_SCORER[moment]
    assert g.entities.player_ids[0] == scorer
    assert any(r.ref == ev.event_id for r in facts_by_key(g)["goal.scorer"].evidence)
    assert g.priority == 5


@pytest.mark.parametrize("seed", SEEDS)
def test_goal_scorer_names(sims, runs, seed):
    insights, _ = runs[seed]
    names = [facts_by_key(i)["goal.scorer"].value for i in insights if i.kind == "goal"]
    assert names == ["Vukovic", "Shapira", "Vukovic"]


@pytest.mark.parametrize("seed", SEEDS)
def test_g2_goal_carries_press_turnover_chain(sims, runs, seed):
    match, truth = sims[seed]
    insights, _ = runs[seed]
    g2 = next(i for i in insights if i.kind == "goal" and facts_by_key(i)["goal.scorer"].value == "Shapira")
    f = facts_by_key(g2)
    assert f["goal.won_ball_by"].value == "Lindqvist"
    assert f["goal.seconds_from_turnover"].value <= 10


@pytest.mark.parametrize("seed", SEEDS)
def test_g3_produces_brace_milestone(sims, runs, seed):
    match, truth = sims[seed]
    insights, _ = runs[seed]
    ev = next(e for e in match.events if e.event_id == truth.scripted_event_ids["G3"])
    ms = [i for i in insights if i.kind == "milestone" and near(i, ev)]
    assert len(ms) == 1
    f = facts_by_key(ms[0])
    assert f["NVL-09.match_goals"].value == 2 and f["NVL-09.match_goals"].previous_value == 1
    assert f["NVL-09.career_goals"].value == 50
    assert ms[0].entities.player_ids == ["NVL-09"]


@pytest.mark.parametrize("seed", SEEDS)
def test_m1_player_tag_cites_sprint(sims, runs, seed):
    match, truth = sims[seed]
    insights, _ = runs[seed]
    m1 = truth.scripted_event_ids["M1"]
    tags = [i for i in insights if i.kind == "player_tag" and i.entities.player_ids == ["SLM-11"]]
    assert len(tags) == 1
    f = facts_by_key(tags[0])
    assert f["SLM-11.sprint_top_speed_kmh"].value == 34.8
    assert any(r.kind == "event" and r.ref == m1 for r in f["SLM-11.sprint_top_speed_kmh"].evidence)
    assert f["match.max_sprint_kmh"].value == 34.8


@pytest.mark.parametrize("seed", SEEDS)
def test_s3_press_change_for_saltmere(runs, seed):
    insights, _ = runs[seed]
    slm = [minute(i) for i in insights if i.kind == "press_change" and i.entities.team_ids == ["SLM"]]
    assert any(58 <= m <= 66 for m in slm), slm
    assert not any(m <= 55 for m in slm), slm


@pytest.mark.parametrize("seed", SEEDS)
def test_s2_marked_more_chaotic_than_s1(runs, seed):
    insights, _ = runs[seed]
    cvc = [i for i in insights if i.kind == "control_vs_chaos"]
    chaos = [i for i in cvc if 25 <= minute(i) < 40 and not i.entities.team_ids]
    assert chaos, "a chaos regime insight should fire during the 25-40' spell"
    s1 = [facts_by_key(i)["match.chaos_5m"].value for i in cvc if minute(i) < 25]
    assert all(facts_by_key(chaos[0])["match.chaos_5m"].value > v for v in s1)
    assert facts_by_key(chaos[0])["match.chaos_5m"].value >= 0.7


@pytest.mark.parametrize("seed", SEEDS)
def test_every_fact_has_valid_evidence(sims, runs, seed):
    match, _ = sims[seed]
    insights, _ = runs[seed]
    ids = {e.event_id for e in match.events}
    kinds = {i.kind for i in insights}
    assert {"goal", "key_pass", "milestone", "player_tag", "press_change", "control_vs_chaos", "momentum_shift", "period_summary"} <= kinds
    for ins in insights:
        assert ins.facts, ins.insight_id
        for f in ins.facts:
            assert f.evidence, f.fact_id
            for r in f.evidence:
                if r.kind == "event":
                    assert r.ref in ids, (f.fact_id, r.ref)
                elif r.window_start_s is not None:
                    assert r.window_start_s <= r.window_end_s


def test_insights_are_deterministic(sims):
    match, _ = sims[2]
    a, _ = run_match(match)
    b, _ = run_match(match)
    assert [i.model_dump_json() for i in a] == [i.model_dump_json() for i in b]
    assert len({i.insight_id for i in a}) == len(a)


def test_hot_path_latency(runs):
    _, timings = runs[7]
    ordered = sorted(timings)
    assert ordered[int(0.95 * (len(ordered) - 1))] < 1e-3


def test_pipeline_never_reads_ground_truth():
    root = Path(__file__).resolve().parents[1] / "regista"
    for pkg in ("state", "detect"):
        for path in (root / pkg).rglob("*.py"):
            src = path.read_text(encoding="utf-8")
            assert "truth" not in src.lower() or "never reads ground truth" in src.lower(), path
            assert "GroundTruth" not in src and "truth.json" not in src, path
