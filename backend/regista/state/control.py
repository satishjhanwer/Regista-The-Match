"""Control vs chaos over the rolling 5-minute window.

Three components, each mapped to [0, 1] where 1 = chaotic:

* turnover rate: open-play turnovers lost (tackle / interception) per minute, / 2.0, clipped
* sequence shortness: 1 - (mean passes per possession - 1) / 7, clipped (1 pass = chaos, 8+ = control)
* transition entropy: conditional Shannon entropy (bits) of the possession-transition sequence,
  i.e. of "does the next on-ball action stay with this team?". 0 = always keep it, 1 = coin flip.

``chaos = 0.4 * turnover + 0.3 * shortness + 0.3 * entropy``; a team's control score is
``1 - chaos`` computed on that team's own possessions. The match-level chaos index pools both
teams (mean turnover rate, pooled sequences, possession-weighted entropy). Scales are set from
the observed ranges in normal play vs the planted spells (see docs/DECISIONS.md).
"""

from __future__ import annotations

import math

from .core import MatchState, MetricUpdate

W_TURNOVER, W_SHORTNESS, W_ENTROPY = 0.4, 0.3, 0.3
TURNOVERS_PER_MIN_MAX = 2.0
SEQ_PASSES_CONTROL = 8.0
MIN_SEQUENCES = 4
WINDOW = "5m"
WINDOW_MIN = 5.0


def binary_entropy(p: float) -> float:
    """Shannon entropy in bits of a coin with P(heads) = ``p``."""
    if p <= 0.0 or p >= 1.0:
        return 0.0
    return -(p * math.log2(p) + (1.0 - p) * math.log2(1.0 - p))


def _clip(v: float) -> float:
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v


def chaos_score(turnovers_per_min: float, mean_seq_passes: float, entropy: float) -> float:
    """Combine the three components into a chaos score in [0, 1] (weights in the module docstring)."""
    shortness = 1.0 - (mean_seq_passes - 1.0) / (SEQ_PASSES_CONTROL - 1.0)
    return W_TURNOVER * _clip(turnovers_per_min / TURNOVERS_PER_MIN_MAX) + W_SHORTNESS * _clip(shortness) + W_ENTROPY * entropy


class ControlChaos:
    """Per-team control scores and the match chaos index over the 5-minute window."""

    def __init__(self) -> None:
        self.control: dict[str, float | None] = {}
        self.chaos: float | None = None
        self.components: dict[str, dict[str, float]] = {}

    def _team(self, st: MatchState, t: str) -> tuple[float, float, float, float, float] | None:
        seqs = st.window(t, "sequences", WINDOW)
        if seqs < MIN_SEQUENCES:
            return None
        kept, lost = st.window(t, "transitions_kept", WINDOW), st.window(t, "transitions_lost", WINDOW)
        to_rate = st.window(t, "turnovers_lost", WINDOW) / WINDOW_MIN
        seq_len = st.window(t, "sequence_passes", WINDOW) / seqs
        ent = binary_entropy(lost / (kept + lost)) if kept + lost else 0.0
        return to_rate, seq_len, ent, seqs, kept + lost

    def apply(self, ev, st: MatchState, out: list[MetricUpdate]) -> None:
        """Recompute the scores when a possession ends."""
        if ev.type != "possession_change":
            return
        per_team = {t: self._team(st, t) for t in st.team_ids}
        for t, c in per_team.items():
            if c is None:
                continue
            to_rate, seq_len, ent, _, _ = c
            control = 1.0 - chaos_score(to_rate, seq_len, ent)
            self.control[t] = control
            self.components[t] = {"turnovers_per_min": to_rate, "mean_sequence_passes": seq_len, "transition_entropy": ent}
            st.emit(out, f"{t}.turnovers_per_min_5m", to_rate, WINDOW)
            st.emit(out, f"{t}.mean_sequence_passes_5m", seq_len, WINDOW)
            st.emit(out, f"{t}.transition_entropy_5m", ent, WINDOW)
            st.emit(out, f"{t}.control_5m", control, WINDOW)
        if all(per_team.values()):
            (to_h, _, ent_h, sq_h, tr_h), (to_a, _, ent_a, sq_a, tr_a) = per_team[st.home_id], per_team[st.away_id]
            to_rate = (to_h + to_a) / 2.0
            seq_len = sum(st.window(t, "sequence_passes", WINDOW) for t in st.team_ids) / (sq_h + sq_a)
            ent = (ent_h * tr_h + ent_a * tr_a) / (tr_h + tr_a) if tr_h + tr_a else 0.0
            self.chaos = chaos_score(to_rate, seq_len, ent)
            self.components["match"] = {"turnovers_per_min": to_rate, "mean_sequence_passes": seq_len, "transition_entropy": ent}
            st.emit(out, "match.turnovers_per_min_5m", to_rate, WINDOW)
            st.emit(out, "match.mean_sequence_passes_5m", seq_len, WINDOW)
            st.emit(out, "match.transition_entropy_5m", ent, WINDOW)
            st.emit(out, "match.chaos_5m", self.chaos, WINDOW)

    def snapshot(self, st: MatchState) -> dict:
        """Current chaos index and control scores."""
        return {"chaos_5m": self.chaos, "control_5m": dict(self.control)}
