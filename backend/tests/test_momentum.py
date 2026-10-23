"""Momentum EWMA: decay mechanics and the planted control / press storylines."""

from __future__ import annotations

import pytest

from regista.contracts.events import match_minute
from regista.state import MatchState
from regista.state.models import ExpectedGoals, PassDifficulty
from regista.state.momentum import Momentum

SEEDS = [1, 2, 3, 4, 5, 7]


def index_series(match):
    mom = Momentum()
    st = MatchState(match.meta, [PassDifficulty(), ExpectedGoals(), mom])
    out = []
    for e in match.events:
        st.apply(e)
        out.append((match_minute(e.period, e.t), mom.index(st)))
    return out, mom, st


def mean_index(series, a, b):
    vals = [v for m, v in series if a <= m < b]
    return sum(vals) / len(vals)


@pytest.mark.parametrize("seed", SEEDS)
def test_momentum_tracks_storylines(sims, seed):
    series, _, _ = index_series(sims[seed][0])
    assert all(-1.0 <= v <= 1.0 for _, v in series)
    s1 = mean_index(series, 2, 20)
    s3 = mean_index(series, 60, 75)
    assert s1 > 0.2, "Northvale should own territory during their control spell"
    assert s3 < s1 - 0.3, "Saltmere's press should swing momentum their way"


def test_momentum_resets_each_period_and_cites_events(sims):
    match, _ = sims[7]
    series, mom, st = index_series(match)
    p2 = next(i for i, e in enumerate(match.events) if e.type == "period_start" and e.period == 2)
    assert series[p2][1] == 0.0
    ids = {e.event_id for e in match.events}
    top = mom.top_contributors("NVL", st.now)
    assert top and set(top) <= ids
