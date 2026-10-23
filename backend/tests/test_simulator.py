"""Simulator contract and storyline tests.

The storyline tests assert that each planted storyline is measurable from the
event stream alone, across several seeds, so the analytics layer has a real
signal to detect rather than one lucky draw.
"""

from __future__ import annotations

import json

import pytest

from regista.contracts.events import PITCH_LENGTH_M, PITCH_WIDTH_M, GroundTruth, MatchFile, format_clock, match_minute
from regista.sim.engine import simulate

SEEDS = [1, 2, 3, 4, 5, 7]


@pytest.fixture(scope="module")
def matches():
    return {seed: simulate(seed=seed) for seed in SEEDS}


def window(events, start_min, end_min):
    return [e for e in events if start_min <= match_minute(e.period, e.t) < end_min]


def test_deterministic_for_same_seed():
    a, _ = simulate(seed=11)
    b, _ = simulate(seed=11)
    assert a.model_dump_json() == b.model_dump_json()


def test_different_seeds_differ():
    a, _ = simulate(seed=11)
    b, _ = simulate(seed=12)
    assert a.model_dump_json() != b.model_dump_json()


def test_round_trips_through_schema(matches):
    match, truth = matches[7]
    again = MatchFile.model_validate(json.loads(match.model_dump_json()))
    assert len(again.events) == len(match.events)
    GroundTruth.model_validate(json.loads(truth.model_dump_json()))


@pytest.mark.parametrize("seed", SEEDS)
def test_scoreline_and_scripted_moments(matches, seed):
    match, truth = matches[seed]
    assert truth.final_score == {"NVL": 2, "SLM": 1}
    goals = [e for e in match.events if e.type == "shot" and e.outcome == "goal"]
    assert [(g.team_id, g.player_id) for g in goals] == [("NVL", "NVL-09"), ("SLM", "SLM-09"), ("NVL", "NVL-09")]
    assert set(truth.scripted_event_ids) == {"G1", "G2", "M1", "G3"}
    by_id = {e.event_id: e for e in match.events}
    sprint = by_id[truth.scripted_event_ids["M1"]]
    assert sprint.type == "sprint" and sprint.player_id == "SLM-11"
    assert sprint.top_speed_kmh == max(e.top_speed_kmh for e in match.events if e.type == "sprint")
    assert by_id[truth.scripted_event_ids["G3"]].body_part == "head"


@pytest.mark.parametrize("seed", SEEDS)
def test_stream_invariants(matches, seed):
    match, _ = matches[seed]
    ev = match.events
    assert 1800 <= len(ev) <= 3200
    assert [e.seq for e in ev] == list(range(len(ev)))
    for prev, cur in zip(ev, ev[1:], strict=False):
        assert cur.elapsed_s >= prev.elapsed_s - 1e-6
        assert (cur.period, cur.t) >= (prev.period, prev.t)
        assert cur.possession_id >= prev.possession_id
    for e in ev:
        assert 0 <= e.x <= PITCH_LENGTH_M and 0 <= e.y <= PITCH_WIDTH_M


@pytest.mark.parametrize("seed", SEEDS)
def test_possession_changes_are_consistent(matches, seed):
    """After a possession change, the next on-ball action belongs to the new team."""
    match, _ = matches[seed]
    on_ball = {"pass", "carry", "shot", "clearance"}
    ev = match.events
    for i, e in enumerate(ev):
        if e.type != "possession_change":
            continue
        nxt = next((n for n in ev[i + 1 :] if n.type in on_ball), None)
        if nxt is not None and nxt.possession_id == e.possession_id:
            assert nxt.team_id == e.to_team_id, (e.event_id, nxt.event_id)


@pytest.mark.parametrize("seed", SEEDS)
def test_realistic_volumes(matches, seed):
    match, truth = matches[seed]
    passes = [e for e in match.events if e.type == "pass"]
    completion = sum(e.outcome == "complete" for e in passes) / len(passes)
    assert 900 <= len(passes) <= 1500
    assert 0.74 <= completion <= 0.88
    assert 15 <= len(truth.shots) <= 45
    mean_xg = sum(s.xg_true for s in truth.shots) / len(truth.shots)
    assert 0.07 <= mean_xg <= 0.25


@pytest.mark.parametrize("seed", SEEDS)
def test_storyline_chaos_spell_has_more_turnovers(matches, seed):
    match, _ = matches[seed]

    def turnovers_per_min(a, b):
        w = window(match.events, a, b)
        return sum(e.type == "possession_change" and e.cause in ("tackle", "interception") for e in w) / (b - a)

    assert turnovers_per_min(25, 40) > turnovers_per_min(0, 25) * 1.3


@pytest.mark.parametrize("seed", SEEDS)
def test_storyline_press_shift_is_measurable(matches, seed):
    match, _ = matches[seed]

    def away_pressures_per_home_pass(a, b):
        w = window(match.events, a, b)
        home_passes = sum(e.type == "pass" and e.team_id == "NVL" for e in w)
        pressures = sum(e.type == "pressure" and e.team_id == "SLM" for e in w)
        return pressures / max(home_passes, 1)

    assert away_pressures_per_home_pass(58, 72) > 1.8 * away_pressures_per_home_pass(40, 58)


def test_format_clock():
    assert format_clock(1, 0) == "0:00"
    assert format_clock(1, 1421) == "23:41"
    assert format_clock(1, 2772) == "45+01:12"
    assert format_clock(2, 1325) == "67:05"
    assert format_clock(2, 2900) == "90+03:20"
