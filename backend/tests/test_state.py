"""Match state engine: rolling windows, attacking frame, ordering, incremental correctness."""

from __future__ import annotations

import random

import pytest

from regista.contracts.events import attacks_right
from regista.state import DecayedSum, MatchState, RollingSum, replay
from regista.state.core import FINAL_THIRD_X


def test_rolling_sum_matches_brute_force():
    rng = random.Random(3)
    r = RollingSum(300.0)
    samples = []
    t = 0.0
    for _ in range(2000):
        t += rng.expovariate(1 / 4.0)
        v = rng.random()
        r.add(t, v)
        samples.append((t, v))
        if rng.random() < 0.1:
            expect = [v for s, v in samples if s > t - 300.0]
            assert r.sum(t) == pytest.approx(sum(expect))
            assert r.count(t) == len(expect)


def test_decayed_sum_half_life():
    d = DecayedSum(240.0)
    d.add(0.0, 1.0)
    assert d.value(240.0) == pytest.approx(0.5)
    d.add(480.0, 1.0)
    assert d.value(480.0) == pytest.approx(1.25)


def test_out_of_order_event_raises(sims):
    match, _ = sims[7]
    st = MatchState(match.meta)
    st.apply(match.events[100])
    with pytest.raises(ValueError):
        st.apply(match.events[50])


def test_windows_match_brute_force(sims):
    match, _ = sims[7]
    st = MatchState(match.meta)
    events = match.events
    for i, ev in enumerate(events):
        st.apply(ev)
        if i % 250 or i == 0:
            continue
        now = ev.elapsed_s
        for team in ("NVL", "SLM"):
            recent = [e for e in events[: i + 1] if e.type == "pass" and e.team_id == team and e.elapsed_s > now - 300]
            assert st.window(team, "passes") == len(recent)
            assert st.window(team, "passes_complete") == sum(e.outcome == "complete" for e in recent)


def test_final_third_uses_attacking_frame(sims):
    match, _ = sims[7]
    st, _ = replay(match.meta, match.events)
    for team in ("NVL", "SLM"):
        expect = 0
        for e in match.events:
            if e.type == "pass" and e.team_id == team and e.outcome == "complete":
                x = e.end_x if attacks_right(match.meta, team, e.period) else 105 - e.end_x
                expect += x >= FINAL_THIRD_X
        assert st.totals[team]["passes_final_third"] == expect
        assert expect > 50


def test_score_and_updates(sims):
    match, _ = sims[7]
    st, updates = replay(match.meta, match.events)
    assert st.score == {"NVL": 2, "SLM": 1}
    assert st.player_goals["NVL-09"] == 2
    assert all(u.window_start_s is None or u.window_start_s <= u.window_end_s == u.elapsed_s for u in updates)
    keys = {u.key for u in updates}
    assert {"NVL.pass_completion_5m", "SLM.possession_share_10m", "NVL.turnovers_lost_5m"} <= keys


def test_replay_is_deterministic(sims):
    match, _ = sims[3]
    _, a = replay(match.meta, match.events)
    _, b = replay(match.meta, match.events)
    assert a == b
