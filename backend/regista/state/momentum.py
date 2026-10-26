"""Momentum: exponentially decayed territorial/threat pressure per team.

Signal per team (weights documented in docs/DECISIONS.md):

* completed pass ending in the final third (attacking frame x >= 70): 1.0
* carry ending in the final third: 0.5
* shot: 10 x xG (so a 0.3 xG chance counts like three final-third entries)

Each contribution decays with a 4-minute half-life on ``elapsed_s``. Both
teams decay at the same rate, so the momentum index ``(H - A) / (H + A)`` only
moves when one side adds threat. Reset at each period start.
"""

from __future__ import annotations

from collections import deque

from .core import FINAL_THIRD_X, MatchState, MetricUpdate
from .rolling import DecayedSum

HALF_LIFE_S = 240.0
W_PASS_FINAL_THIRD = 1.0
W_CARRY_FINAL_THIRD = 0.5
W_SHOT_PER_XG = 10.0
FALLBACK_XG = 0.1


class Momentum:
    """Per-team decayed threat, the momentum index and its top contributing events (see module docstring)."""

    def __init__(self, half_life_s: float = HALF_LIFE_S) -> None:
        self.half_life_s = half_life_s
        self.sums: dict[str, DecayedSum] = {}
        self.recent: dict[str, deque[tuple[float, str, float]]] = {}

    def _ensure(self, st: MatchState) -> None:
        if not self.sums:
            self.sums = {t: DecayedSum(self.half_life_s) for t in st.team_ids}
            self.recent = {t: deque(maxlen=16) for t in st.team_ids}

    def weight(self, ev, st: MatchState) -> float:
        """Threat weight of an event for its team (0 when it adds no threat)."""
        if ev.type == "pass" and ev.outcome == "complete" and st.rel_x(ev.team_id, ev.end_x) >= FINAL_THIRD_X:
            return W_PASS_FINAL_THIRD
        if ev.type == "carry" and st.rel_x(ev.team_id, ev.end_x) >= FINAL_THIRD_X:
            return W_CARRY_FINAL_THIRD
        if ev.type == "shot":
            return W_SHOT_PER_XG * st.shot_xg.get(ev.event_id, FALLBACK_XG)
        return 0.0

    def apply(self, ev, st: MatchState, out: list[MetricUpdate]) -> None:
        """Add the event's threat, or reset at a period start."""
        self._ensure(st)
        if ev.type == "period_start":
            for t in st.team_ids:
                self.sums[t].reset(st.now)
                self.recent[t].clear()
            return
        if ev.team_id is None or ev.type not in ("pass", "carry", "shot"):
            return
        w = self.weight(ev, st)
        if w <= 0.0:
            return
        self.sums[ev.team_id].add(st.now, w)
        self.recent[ev.team_id].append((st.now, ev.event_id, w))
        lo, hi = max(st.period_start_s, st.now - 2 * self.half_life_s), st.now
        for t in st.team_ids:
            out.append(MetricUpdate(f"{t}.momentum", self.value(t, st.now), st.now, lo, hi))
        out.append(MetricUpdate("match.momentum_index", self.index(st), st.now, lo, hi))

    def value(self, team_id: str, now: float) -> float:
        """A team's decayed threat at ``now``."""
        return self.sums[team_id].value(now) if self.sums else 0.0

    def index(self, st: MatchState) -> float:
        """Home-positive momentum index in [-1, 1]."""
        h, a = self.value(st.home_id, st.now), self.value(st.away_id, st.now)
        return (h - a) / (h + a) if h + a > 0 else 0.0

    def share(self, team_id: str, st: MatchState) -> float:
        """A team's share of current momentum, in [0, 1] (0.5 when nobody has any)."""
        h, a = self.value(st.home_id, st.now), self.value(st.away_id, st.now)
        return (self.value(team_id, st.now) / (h + a)) if h + a > 0 else 0.5

    def top_contributors(self, team_id: str, now: float, n: int = 3) -> list[str]:
        """Event ids that contribute most to the team's current momentum (after decay)."""
        scored = [(w * 0.5 ** ((now - t) / self.half_life_s), eid) for t, eid, w in self.recent.get(team_id, ())]
        return [eid for _, eid in sorted(scored, reverse=True)[:n]]

    def snapshot(self, st: MatchState) -> dict:
        """Momentum share per team."""
        return {"momentum": {t: round(self.share(t, st), 3) for t in st.team_ids}}
