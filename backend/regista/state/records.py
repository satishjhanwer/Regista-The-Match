"""Speed thresholds, match records and player milestones.

* Sprint threshold: a sprint at or above 30 km/h is tagged.
* Match records (running max): sprint top speed, shot speed, pass ball speed. A new record is
  only announced once the match is 10 minutes old, so the first few events do not all "set records".
* Milestones: brace / hat-trick in this match; career goal landmarks (first goal, every 25th);
  career appearance landmarks (every 50th) at kickoff. Career numbers come from the roster in
  ``MatchMeta`` (career totals before this match) plus what happens in the match.
"""

from __future__ import annotations

from dataclasses import dataclass

from .core import MatchState, MetricUpdate

SPRINT_THRESHOLD_KMH = 30.0
RECORD_MIN_ELAPSED_S = 600.0
GOAL_LANDMARK_EVERY = 25
APPEARANCE_LANDMARK_EVERY = 50
MATCH_GOAL_MILESTONES = {2: "brace", 3: "hat_trick"}


@dataclass(frozen=True)
class SpeedMark:
    """One notable speed: a match record and/or a sprint over the threshold.

    ``kind`` is sprint, shot_speed or pass_speed; ``previous_*`` describe the record it beat, if any.
    ``is_record`` means a new match record (only after the first 10 minutes); ``over_threshold`` a sprint of 30 km/h+.
    """

    kind: str
    value_kmh: float
    event_id: str
    player_id: str
    team_id: str
    elapsed_s: float
    previous_kmh: float | None = None
    previous_event_id: str | None = None
    is_record: bool = False
    over_threshold: bool = False


@dataclass(frozen=True)
class Milestone:
    """A player milestone: brace, hat_trick, career_goal or career_appearance, with old and new values."""

    kind: str
    player_id: str
    team_id: str
    value: int
    previous_value: int | None
    event_id: str
    elapsed_s: float


_SPEED_FIELDS = {"sprint": ("sprint", "top_speed_kmh"), "shot": ("shot_speed", "shot_speed_kmh"), "pass": ("pass_speed", "ball_speed_kmh")}


class Records:
    """Speed thresholds, running match records and player milestones."""

    def __init__(self) -> None:
        self.best: dict[str, SpeedMark] = {}
        self.marks: list[SpeedMark] = []  # notable marks only: records and threshold hits, in order
        self.milestones: list[Milestone] = []

    def apply(self, ev, st: MatchState, out: list[MetricUpdate]) -> None:
        """Check the event for speeds, goals (milestones) and kickoff (appearance landmarks)."""
        if ev.type == "period_start" and ev.period == 1:
            self._appearances(ev, st)
        spec = _SPEED_FIELDS.get(ev.type)
        if spec is not None and ev.player_id:
            self._speed(spec[0], getattr(ev, spec[1]), ev, st, out)
        if ev.type == "shot" and ev.outcome == "goal":
            self._goal(ev, st)

    def _speed(self, kind: str, value: float, ev, st: MatchState, out: list[MetricUpdate]) -> None:
        prev = self.best.get(kind)
        new_best = prev is None or value > prev.value_kmh
        is_record = new_best and st.now >= RECORD_MIN_ELAPSED_S
        over = kind == "sprint" and value >= SPRINT_THRESHOLD_KMH
        mark = SpeedMark(
            kind=kind,
            value_kmh=value,
            event_id=ev.event_id,
            player_id=ev.player_id,
            team_id=ev.team_id,
            elapsed_s=st.now,
            previous_kmh=prev.value_kmh if prev else None,
            previous_event_id=prev.event_id if prev else None,
            is_record=is_record,
            over_threshold=over,
        )
        if new_best:
            self.best[kind] = mark
            st.emit(out, f"match.max_{kind}_kmh", value)
        if is_record or over:
            self.marks.append(mark)
        if over:
            st.emit(out, f"{ev.player_id}.sprint_kmh", value)

    def _goal(self, ev, st: MatchState) -> None:
        pid, team = ev.player_id, ev.team_id
        n = st.player_goals[pid]  # core counters ran first
        if n in MATCH_GOAL_MILESTONES:
            self.milestones.append(Milestone(MATCH_GOAL_MILESTONES[n], pid, team, n, n - 1, ev.event_id, st.now))
        career = st.players[pid].career_goals + n
        if career == 1 or career % GOAL_LANDMARK_EVERY == 0:
            self.milestones.append(Milestone("career_goal", pid, team, career, career - 1, ev.event_id, st.now))

    def _appearances(self, ev, st: MatchState) -> None:
        for pid, p in st.players.items():
            apps = p.career_appearances + 1
            if apps % APPEARANCE_LANDMARK_EVERY == 0:
                self.milestones.append(Milestone("career_appearance", pid, st.team_of[pid], apps, apps - 1, ev.event_id, st.now))

    def snapshot(self, st: MatchState) -> dict:
        """Current match record per speed kind."""
        return {"records": {k: {"kmh": m.value_kmh, "player_id": m.player_id, "event_id": m.event_id} for k, m in self.best.items()}}
