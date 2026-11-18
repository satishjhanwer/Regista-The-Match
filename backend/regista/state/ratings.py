"""Player match ratings from published action weights (``models/ratings.json``), explainable action by action.

A rating starts at ``base`` and moves with what the player did, in five categories:

- goals: ``goal`` per goal, plus ``per_xg_shot`` per xG of every shot (a good chance counts even if missed)
- chances created: ``per_xg_created`` per xG of shots the player's pass set up, plus ``assist`` per goal assisted
- passing: ``per_difficulty_completed`` x difficulty (1 - P(complete)) for every completed pass
- defending: tackles won, interceptions and pressures; for goalkeepers ``per_xg_saved`` per xG of every shot saved
- mistakes (points lost): ``per_p_failed`` x P(complete) for every failed pass (an easy one costs more), tackles lost

The rating is clipped to [``min``, ``max``] and every category's points are kept, so a graphic can say why.
The weights are set by hand and published, not fitted: no answer key says "how well did he play".
"""

from __future__ import annotations

import json
from collections import defaultdict

from .core import MatchState, MetricUpdate
from .logistic import MODELS_DIR

CATEGORIES = ("goals", "chances_created", "passing", "defending", "mistakes")


def load_weights(name: str = "ratings") -> dict[str, float]:
    """The published rating weights."""
    return json.loads((MODELS_DIR / f"{name}.json").read_text(encoding="utf-8"))


class PlayerRatings:
    """Running points per player and category; needs PassDifficulty and ExpectedGoals to run first."""

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self.w = weights or load_weights()
        self.points: dict[str, dict[str, float]] = defaultdict(lambda: dict.fromkeys(CATEGORIES, 0.0))
        self.actions: dict[str, int] = defaultdict(int)

    def _add(self, pid: str, category: str, v: float) -> None:
        self.points[pid][category] += v

    def apply(self, ev, st: MatchState, out: list[MetricUpdate]) -> None:
        """Credit the event to the players involved."""
        pid, typ, w = ev.player_id, ev.type, self.w
        if pid is None:
            return
        self.actions[pid] += 1
        if typ == "pass":
            p = st.pass_p.get(ev.event_id, 0.5)
            if ev.outcome == "complete":
                self._add(pid, "passing", w["per_difficulty_completed"] * (1.0 - p))
            else:
                self._add(pid, "mistakes", w["per_p_failed"] * p)
        elif typ == "shot":
            xg = st.shot_xg.get(ev.event_id, 0.0)
            self._add(pid, "goals", w["per_xg_shot"] * xg + (w["goal"] if ev.outcome == "goal" else 0.0))
            setup = st.passes.get(ev.assist_event_id) if ev.assist_event_id else None
            if setup is not None:
                bonus = w["assist"] if ev.outcome == "goal" else 0.0
                self._add(setup.player_id, "chances_created", w["per_xg_created"] * xg + bonus)
        elif typ == "save":
            self._add(pid, "defending", w["per_xg_saved"] * st.shot_xg.get(ev.shot_event_id, 0.0))
        elif typ == "tackle":
            if ev.outcome == "won":
                self._add(pid, "defending", w["tackle_won"])
            else:
                self._add(pid, "mistakes", w["tackle_lost"])
        elif typ == "interception":
            self._add(pid, "defending", w["interception"])
        elif typ == "pressure":
            self._add(pid, "defending", w["pressure"])

    def rating(self, pid: str) -> float:
        """The player's rating now, one decimal."""
        pts = self.points.get(pid)
        if pts is None:
            return self.w["base"]
        raw = self.w["base"] + sum(v for c, v in pts.items() if c != "mistakes") - pts["mistakes"]
        return round(min(self.w["max"], max(self.w["min"], raw)), 1)

    def breakdown(self, pid: str) -> dict[str, float]:
        """Points per category, rounded to one decimal (mistakes as points lost, a positive number)."""
        return {c: round(v, 1) for c, v in self.points.get(pid, dict.fromkeys(CATEGORIES, 0.0)).items()}

    def snapshot(self, st: MatchState) -> dict:
        """Every rated player's rating."""
        return {"ratings": {pid: self.rating(pid) for pid in self.points}}
