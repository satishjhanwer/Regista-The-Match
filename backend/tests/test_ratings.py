"""Player ratings: re-derived from raw events, explained by their facts, shown to the right viewers, ids untouched."""

from __future__ import annotations

import json
import statistics

import pytest

from regista.agents.context import ToolBox, capture
from regista.agents.profiles import PRESETS, display_for, profile_from_params
from regista.detect import InsightPipeline
from regista.detect.detectors import RatingDetector, default_detectors
from regista.detect.predict import Predictor
from regista.state import PlayerRatings, build_state
from regista.state.ratings import load_weights


def run(match, detectors=None, predictor=None):
    pipe = InsightPipeline(match.meta, detectors=detectors, predictor=predictor)
    for ev in match.events:
        pipe.process(ev)
    return pipe


def expected_ratings(match, st) -> dict[str, float]:
    """The rating rules applied by hand to the raw events (pass and shot probabilities from the state's models)."""
    w = load_weights()
    pts: dict[str, float] = {}
    passes = {e.event_id: e for e in match.events if e.type == "pass"}

    def add(pid, v):
        pts[pid] = pts.get(pid, 0.0) + v

    for e in match.events:
        if e.player_id is None:
            continue
        add(e.player_id, 0.0)
        if e.type == "pass":
            p = st.pass_p[e.event_id]
            add(e.player_id, w["per_difficulty_completed"] * (1 - p) if e.outcome == "complete" else -w["per_p_failed"] * p)
        elif e.type == "shot":
            xg = st.shot_xg[e.event_id]
            add(e.player_id, w["per_xg_shot"] * xg + (w["goal"] if e.outcome == "goal" else 0))
            if e.assist_event_id in passes:
                add(passes[e.assist_event_id].player_id, w["per_xg_created"] * xg + (w["assist"] if e.outcome == "goal" else 0))
        elif e.type == "save":
            add(e.player_id, w["per_xg_saved"] * st.shot_xg[e.shot_event_id])
        elif e.type == "tackle":
            add(e.player_id, w["tackle_won"] if e.outcome == "won" else -w["tackle_lost"])
        elif e.type == "interception":
            add(e.player_id, w["interception"])
        elif e.type == "pressure":
            add(e.player_id, w["pressure"])
    return {pid: round(min(w["max"], max(w["min"], w["base"] + v)), 1) for pid, v in pts.items()}


@pytest.mark.parametrize("seed", [1, 7])
def test_every_rating_matches_the_raw_events(sims, seed):
    match, _ = sims[seed]
    st = build_state(match.meta)
    for ev in match.events:
        st.apply(ev)
    comp = st.component(PlayerRatings)
    got = {pid: comp.rating(pid) for pid in comp.points}
    want = expected_ratings(match, st)
    assert got.keys() == want.keys()
    assert all(abs(got[p] - want[p]) <= 0.1 for p in got), {p: (got[p], want[p]) for p in got if abs(got[p] - want[p]) > 0.1}


def test_published_weights_give_a_sane_spread(sims):
    ratings = []
    for seed in (1, 2, 3, 4, 5):
        match, _ = sims[seed]
        st = build_state(match.meta)
        for ev in match.events:
            st.apply(ev)
        comp = st.component(PlayerRatings)
        ratings += [comp.rating(pid) for pid in comp.points]
    assert 6.5 <= statistics.mean(ratings) <= 7.2
    assert 0.4 <= statistics.pstdev(ratings) <= 0.9
    assert min(ratings) >= 5.5 and max(ratings) < 10.0  # nobody pinned to the cap


def test_rating_insights_explain_themselves(sims):
    match, _ = sims[7]
    pipe = run(match)
    comp = pipe.state.component(PlayerRatings)
    ratings = [i for i in pipe.insights if i.kind == "player_rating"]
    assert {i.clock.period for i in ratings} == {1, 2}
    for period in (1, 2):
        top = [i for i in ratings if i.clock.period == period and i.priority == 3]
        assert sorted(i.entities.team_ids[0] for i in top) == ["NVL", "SLM"]
    full_time_top = {i.entities.team_ids[0]: i.entities.player_ids[0] for i in ratings if i.clock.period == 2 and i.priority == 3}
    assert full_time_top == {"NVL": "NVL-09", "SLM": "SLM-09"}  # the brace and the equaliser
    for i in (r for r in ratings if r.clock.period == 2):
        pid = i.entities.player_ids[0]
        facts = {f.key: f.value for f in i.facts}
        assert facts[f"{pid}.match_rating"] == comp.rating(pid)
        for cat, pts in comp.breakdown(pid).items():
            assert facts.get(f"{pid}.rating_{cat}", 0.0 if pts < 0.1 else None) == (pts if pts >= 0.1 else 0.0)
        assert all(i.insight_id.startswith(f"{match.meta.match_id}-RTG-") for i in ratings)


def test_ratings_never_renumber_the_moments(sims):
    match, _ = sims[7]

    class Silent(Predictor):
        def step(self, ev, new_kinds, st):
            return []

    with_ratings = [i for i in run(match).insights if "-INS-" in i.insight_id]
    without = run(match, [d for d in default_detectors() if not isinstance(d, RatingDetector)], Silent()).insights
    assert [i.model_dump() for i in with_ratings] == [i.model_dump() for i in without]


def test_only_followers_see_the_other_ratings(sims):
    match, _ = sims[7]
    ratings = [i for i in run(match).insights if i.kind == "player_rating"]
    for p in PRESETS.values():
        for i in ratings:
            shown = display_for(i, p) is not None
            followed = p.focus_player_id in i.entities.player_ids
            if i.priority < 3:
                assert shown == followed, (p.profile_id, i.why_it_matters_hint)
    lindqvist = profile_from_params("focus-hi-nvl09", player="SLM-06")
    assert [i.entities.player_ids[0] for i in ratings if display_for(i, lindqvist)] == ["SLM-06", "SLM-06"]


def test_the_analyst_can_cite_a_rating(sims):
    match, _ = sims[7]
    pipe = run(match)
    out = json.loads(ToolBox(capture(pipe.state, None)).get_player("NVL-09"))
    rating = next(s for s in out["stats"] if s["label"] == "Vukovic match rating")
    assert rating["value"] == pipe.state.component(PlayerRatings).rating("NVL-09") == 9.5
