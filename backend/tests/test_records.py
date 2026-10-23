"""Speed thresholds, match records and milestones against the scripted moments."""

from __future__ import annotations

import pytest

from regista.state import replay
from regista.state.records import Records

SEEDS = [1, 2, 3, 4, 5, 7]


@pytest.mark.parametrize("seed", SEEDS)
def test_m1_sprint_is_threshold_hit_and_match_record(sims, seed):
    match, truth = sims[seed]
    rec = Records()
    replay(match.meta, match.events, [rec])
    m1 = truth.scripted_event_ids["M1"]
    over = [m for m in rec.marks if m.kind == "sprint" and m.over_threshold]
    assert [m.event_id for m in over] == [m1]
    assert over[0].is_record and over[0].player_id == "SLM-11" and over[0].value_kmh == 34.8
    assert rec.best["sprint"].event_id == m1
    assert {"shot_speed", "pass_speed"} <= set(rec.best)


@pytest.mark.parametrize("seed", SEEDS)
def test_milestones(sims, seed):
    match, truth = sims[seed]
    rec = Records()
    replay(match.meta, match.events, [rec])
    got = {(m.kind, m.player_id, m.value, m.event_id) for m in rec.milestones}
    g3 = truth.scripted_event_ids["G3"]
    assert ("brace", "NVL-09", 2, g3) in got
    assert ("career_goal", "NVL-09", 50, g3) in got
    kickoff = match.events[0].event_id
    assert ("career_appearance", "SLM-06", 100, kickoff) in got
    assert len(got) == 3
