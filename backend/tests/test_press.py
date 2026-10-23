"""Press intensity metric and the gated CUSUM change-point on the planted S3 high press."""

from __future__ import annotations

import pytest

from regista.contracts.events import match_minute
from regista.state import replay
from regista.state.press import Press

SEEDS = [1, 2, 3, 4, 5, 7]


def run(match):
    press = Press()
    _, updates = replay(match.meta, match.events, [press])
    return press, updates


@pytest.mark.parametrize("seed", SEEDS)
def test_cusum_flags_s3_and_not_first_55_minutes(sims, seed):
    press, _ = run(sims[seed][0])
    slm = [match_minute(a.period, a.t) for a in press.alarms if a.team_id == "SLM"]
    assert any(58 <= m <= 66 for m in slm), slm
    assert not any(m <= 55 for m in slm), slm


@pytest.mark.parametrize("seed", SEEDS)
def test_press_ratio_rises_in_s3(sims, seed):
    match, _ = sims[seed]
    _, updates = run(match)
    minute = {e.elapsed_s: match_minute(e.period, e.t) for e in match.events}
    series = [(minute[u.elapsed_s], u.value) for u in updates if u.key == "SLM.pressures_per_opp_pass_5m"]

    def mean(a, b):
        vals = [v for m, v in series if a <= m < b]
        return sum(vals) / len(vals)

    assert mean(62, 72) > 1.8 * mean(45, 57)


def test_alarm_evidence_is_consistent(sims):
    match, _ = sims[7]
    press, updates = run(match)
    ids = {e.event_id for e in match.events}
    first = next(a for a in press.alarms if a.team_id == "SLM")
    assert first.change_start_s <= first.elapsed_s
    assert first.recent_pressed_share > first.baseline_pressed_share
    assert first.pressure_event_ids and set(first.pressure_event_ids) <= ids
    assert any(u.key == "SLM.press_alarm" and u.window_start_s == first.change_start_s for u in updates)
