"""Model-backed components: pass difficulty (and, below, expected goals)."""

from __future__ import annotations

from .core import MatchState, MetricUpdate
from .logistic import LogisticModel, pass_features


class PassDifficulty:
    """Scores every pass with ``P(complete)`` from the offline-fitted model; difficulty = 1 - P.

    Also tracks completion over expected per team: completed minus expected passes,
    divided by attempts, over the rolling windows.
    """

    def __init__(self, model: LogisticModel | None = None) -> None:
        self.model = model or LogisticModel.load("pass_model")
        self.p_complete: dict[str, float] = {}

    def difficulty(self, event_id: str) -> float | None:
        p = self.p_complete.get(event_id)
        return None if p is None else 1.0 - p

    def apply(self, ev, st: MatchState, out: list[MetricUpdate]) -> None:
        if ev.type != "pass":
            return
        p = self.model.predict(pass_features(ev))
        self.p_complete[ev.event_id] = p
        st.count(ev.team_id, "passes_expected", p)
        st.emit(out, f"{ev.team_id}.pass_difficulty", 1.0 - p)
        n = st.window(ev.team_id, "passes")
        coe = (st.window(ev.team_id, "passes_complete") - st.window(ev.team_id, "passes_expected")) / n
        st.emit(out, f"{ev.team_id}.completion_over_expected_5m", coe, "5m")
