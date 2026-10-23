"""Model-backed components: pass difficulty and expected goals.

Both load coefficients fitted offline by ``scripts/fit_models.py`` (seeds 1-5)
and only predict at runtime.
"""

from __future__ import annotations

from .core import MatchState, MetricUpdate
from .logistic import LogisticModel, pass_features, shot_features


class PassDifficulty:
    """Scores every pass with ``P(complete)``; difficulty = 1 - P.

    Also tracks completion over expected per team: completed minus expected
    passes, divided by attempts, over the 5-minute window.
    """

    def __init__(self, model: LogisticModel | None = None) -> None:
        self.model = model or LogisticModel.load("pass_model")

    def apply(self, ev, st: MatchState, out: list[MetricUpdate]) -> None:
        if ev.type != "pass":
            return
        p = self.model.predict(pass_features(ev))
        st.pass_p[ev.event_id] = p
        st.count(ev.team_id, "passes_expected", p)
        st.emit(out, f"{ev.team_id}.pass_difficulty", 1.0 - p)
        n = st.window(ev.team_id, "passes")
        coe = (st.window(ev.team_id, "passes_complete") - st.window(ev.team_id, "passes_expected")) / n
        st.emit(out, f"{ev.team_id}.completion_over_expected_5m", coe, "5m")


class ExpectedGoals:
    """xG for every shot, plus per-team running and rolling xG totals."""

    def __init__(self, model: LogisticModel | None = None) -> None:
        self.model = model or LogisticModel.load("xg_model")

    def apply(self, ev, st: MatchState, out: list[MetricUpdate]) -> None:
        if ev.type != "shot":
            return
        xg = self.model.predict(shot_features(ev))
        st.shot_xg[ev.event_id] = xg
        st.count(ev.team_id, "xg", xg)
        st.emit(out, f"{ev.team_id}.shot_xg", xg)
        st.emit(out, f"{ev.team_id}.xg_total", st.totals[ev.team_id]["xg"])
        st.emit(out, f"{ev.team_id}.xg_10m", st.window(ev.team_id, "xg", "10m"), "10m")

    def snapshot(self, st: MatchState) -> dict:
        return {"xg": {t: round(st.totals[t]["xg"], 3) for t in st.team_ids}}
