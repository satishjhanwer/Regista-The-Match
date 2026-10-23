"""Control vs chaos: planted S1 control spell and S2 chaos spell."""

from __future__ import annotations

import pytest

from regista.contracts.events import match_minute
from regista.state import replay
from regista.state.control import ControlChaos, binary_entropy, chaos_score

SEEDS = [1, 2, 3, 4, 5, 7]


def samples(match, key):
    _, updates = replay(match.meta, match.events, [ControlChaos()])
    minute_of = {}
    for e in match.events:
        minute_of.setdefault(e.elapsed_s, match_minute(e.period, e.t))
    return [(minute_of[u.elapsed_s], u.value) for u in updates if u.key == key]


def mean_between(series, a, b):
    vals = [v for m, v in series if a <= m < b]
    assert vals, (a, b)
    return sum(vals) / len(vals)


def test_score_bounds_and_entropy():
    assert binary_entropy(0.5) == pytest.approx(1.0)
    assert binary_entropy(0.0) == 0.0
    assert chaos_score(0.0, 20.0, 0.0) == 0.0
    assert chaos_score(10.0, 1.0, 1.0) == pytest.approx(1.0)


@pytest.mark.parametrize("seed", SEEDS)
def test_s2_chaos_spell_more_chaotic_than_s1(sims, seed):
    chaos = samples(sims[seed][0], "match.chaos_5m")
    assert all(0.0 <= v <= 1.0 for _, v in chaos)
    assert mean_between(chaos, 28, 40) > mean_between(chaos, 0, 25) + 0.15


@pytest.mark.parametrize("seed", SEEDS)
def test_s1_northvale_control_above_s2(sims, seed):
    control = samples(sims[seed][0], "NVL.control_5m")
    assert mean_between(control, 0, 25) > mean_between(control, 25, 40) + 0.1
