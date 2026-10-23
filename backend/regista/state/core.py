"""Incremental match state: per-team rolling windows and match totals.

``MatchState.apply(event)`` consumes one event and returns the metrics it
changed as ``MetricUpdate`` records. Time is ``elapsed_s`` (monotonic); events
must arrive in non-decreasing ``elapsed_s`` order. Every update is O(1)
amortized. Geometry is converted to the acting team's attacking frame
(attacking towards x = 105) via ``attacks_right``.

Analytical components (pass difficulty, xG, momentum, control vs chaos,
press, records) plug in as objects with ``apply(event, state, out)`` and run
after the core counters for every event.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Protocol

from ..contracts.events import PITCH_LENGTH_M, MatchMeta, Player, attacks_right
from .rolling import RollingSum

WINDOWS_S: dict[str, float] = {"5m": 300.0, "10m": 600.0}
FINAL_THIRD_X = 70.0
LONG_PASS_M = 32.0
LONG_LOFTED_PASS_M = 25.0
ON_BALL = frozenset({"pass", "carry", "shot", "clearance"})
TURNOVER_CAUSES = frozenset({"tackle", "interception"})


@dataclass(frozen=True, slots=True)
class MetricUpdate:
    """One metric value at one instant. Window bounds are ``elapsed_s`` and double as evidence refs."""

    key: str
    value: float
    elapsed_s: float
    window_start_s: float | None = None
    window_end_s: float | None = None


def is_long_ball(ev) -> bool:
    """A non-cross pass over 32 m, or a lofted (high) non-cross pass over 25 m."""
    return not ev.is_cross and (ev.length_m > LONG_PASS_M or (ev.height == "high" and ev.length_m > LONG_LOFTED_PASS_M))


class Component(Protocol):
    def apply(self, ev, st: MatchState, out: list[MetricUpdate]) -> None: ...


class TeamWindows:
    """Named rolling sums, one per window length in ``WINDOWS_S``."""

    __slots__ = ("_w",)

    def __init__(self) -> None:
        self._w: dict[str, dict[str, RollingSum]] = {}

    def add(self, name: str, t: float, v: float = 1.0) -> None:
        w = self._w.get(name)
        if w is None:
            w = self._w[name] = {label: RollingSum(s) for label, s in WINDOWS_S.items()}
        for r in w.values():
            r.add(t, v)

    def sum(self, name: str, label: str, now: float) -> float:
        w = self._w.get(name)
        return w[label].sum(now) if w else 0.0


class MatchState:
    def __init__(self, meta: MatchMeta, components: list[Component] | None = None) -> None:
        self.meta = meta
        self.home_id, self.away_id = meta.home.team_id, meta.away.team_id
        self.team_ids = (self.home_id, self.away_id)
        self.players: dict[str, Player] = {}
        self.team_of: dict[str, str] = {}
        for team in (meta.home, meta.away):
            for p in team.players:
                self.players[p.player_id] = p
                self.team_of[p.player_id] = team.team_id

        self.now = 0.0
        self.period = 1
        self.period_start_s = 0.0
        self.n_events = 0
        self.last_event = None
        self.score = {t: 0 for t in self.team_ids}
        self.player_goals: dict[str, int] = defaultdict(int)
        self.goal_events: dict[str, list[str]] = defaultdict(list)  # player_id -> goal event ids, in order
        self.totals: dict[str, dict[str, float]] = {t: defaultdict(float) for t in self.team_ids}
        self.windows: dict[str, TeamWindows] = {t: TeamWindows() for t in self.team_ids}
        self.passes: dict[str, object] = {}  # event_id -> PassEvent, for assist / key-pass lookups
        self.pass_p: dict[str, float] = {}  # event_id -> P(complete), filled by PassDifficulty
        self.shot_xg: dict[str, float] = {}  # event_id -> xG, filled by ExpectedGoals

        self.poss_id = -1
        self.poss_team: str | None = None
        self.poss_passes = 0
        self.poss_start = None  # the possession_change event that started the current possession
        self.last_on_ball_team: str | None = None
        self._attacks_right: dict[tuple[str, int], bool] = {(t, p): attacks_right(meta, t, p) for t in self.team_ids for p in (1, 2)}
        self.components: list[Component] = list(components or [])

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def component(self, cls):
        """The first plugged-in component of type ``cls``, or None."""
        return next((c for c in self.components if isinstance(c, cls)), None)

    def opp(self, team_id: str) -> str:
        return self.away_id if team_id == self.home_id else self.home_id

    def rel_x(self, team_id: str, x: float, period: int | None = None) -> float:
        """x in ``team_id``'s attacking frame (0 = own goal line, 105 = opponent's)."""
        return x if self._attacks_right[(team_id, period or self.period)] else PITCH_LENGTH_M - x

    def window(self, team_id: str, name: str, label: str = "5m") -> float:
        return self.windows[team_id].sum(name, label, self.now)

    def window_bounds(self, label: str) -> tuple[float, float]:
        return max(0.0, self.now - WINDOWS_S[label]), self.now

    def ratio(self, team_id: str, num: str, den: str, label: str = "5m") -> float | None:
        d = self.window(team_id, den, label)
        return self.window(team_id, num, label) / d if d else None

    def emit(self, out: list[MetricUpdate], key: str, value: float, label: str | None = None) -> None:
        if label is None:
            out.append(MetricUpdate(key, value, self.now))
        else:
            lo, hi = self.window_bounds(label)
            out.append(MetricUpdate(key, value, self.now, lo, hi))

    def count(self, team_id: str, name: str, v: float = 1.0) -> None:
        """Add to the team's match total and rolling windows."""
        self.totals[team_id][name] += v
        self.windows[team_id].add(name, self.now, v)

    # ------------------------------------------------------------------ #
    # Event application
    # ------------------------------------------------------------------ #
    def apply(self, ev) -> list[MetricUpdate]:
        if ev.elapsed_s < self.now - 1e-6:
            raise ValueError(f"event {ev.event_id} out of order: elapsed_s {ev.elapsed_s} < {self.now}")
        self.now = ev.elapsed_s
        self.period = ev.period
        out: list[MetricUpdate] = []

        typ = ev.type
        if typ == "period_start":
            self.period_start_s = ev.elapsed_s
            self.last_on_ball_team = None
        elif typ == "possession_change":
            self._on_possession_change(ev, out)

        if typ in ON_BALL and ev.team_id is not None:
            self._on_ball(ev)
        if typ == "pass":
            self._on_pass(ev, out)
        elif typ == "carry":
            if ev.team_id and self.rel_x(ev.team_id, ev.end_x) >= FINAL_THIRD_X:
                self.count(ev.team_id, "carries_final_third")
        elif typ == "pressure":
            self.count(ev.team_id, "pressures")
        elif typ == "shot":
            self.count(ev.team_id, "shots")
            if ev.outcome == "goal":
                self.score[ev.team_id] += 1
                self.player_goals[ev.player_id] += 1
                self.goal_events[ev.player_id].append(ev.event_id)
                self.emit(out, f"{ev.team_id}.goals", self.score[ev.team_id])

        for comp in self.components:
            comp.apply(ev, self, out)
        self.last_event = ev
        self.n_events += 1
        return out

    def _on_ball(self, ev) -> None:
        prev = self.last_on_ball_team
        if prev is not None:
            self.count(prev, "transitions_kept" if prev == ev.team_id else "transitions_lost")
        self.last_on_ball_team = ev.team_id

    def _on_possession_change(self, ev, out: list[MetricUpdate]) -> None:
        if self.poss_team is not None:
            self.count(self.poss_team, "sequences")
            self.count(self.poss_team, "sequence_passes", self.poss_passes)
        frm = ev.from_team_id
        if frm is not None and ev.cause in TURNOVER_CAUSES:
            self.count(frm, "turnovers_lost")
            self.emit(out, f"{frm}.turnovers_lost_5m", self.window(frm, "turnovers_lost"), "5m")
        self.poss_id, self.poss_team, self.poss_passes, self.poss_start = ev.possession_id, ev.to_team_id, 0, ev

    def _on_pass(self, ev, out: list[MetricUpdate]) -> None:
        team = ev.team_id
        self.passes[ev.event_id] = ev
        if team == self.poss_team:
            self.poss_passes += 1
        complete = ev.outcome == "complete"
        self.count(team, "passes")
        if complete:
            self.count(team, "passes_complete")
            if self.rel_x(team, ev.end_x) >= FINAL_THIRD_X:
                self.count(team, "passes_final_third")
        if is_long_ball(ev):
            self.count(team, "long_passes")
        if ev.pressure.defenders_within_5m >= 1:
            self.count(team, "pressed_passes")
        for label in WINDOWS_S:
            n = self.window(team, "passes", label)
            self.emit(out, f"{team}.pass_completion_{label}", self.window(team, "passes_complete", label) / n, label)
            self.emit(out, f"{team}.long_ball_share_{label}", self.window(team, "long_passes", label) / n, label)
            total = n + self.window(self.opp(team), "passes", label)
            self.emit(out, f"{team}.possession_share_{label}", n / total, label)

    # ------------------------------------------------------------------ #
    # Read side
    # ------------------------------------------------------------------ #
    def snapshot(self) -> dict:
        """Plain-dict view of the current state, for tools and debugging."""
        snap: dict = {"elapsed_s": self.now, "period": self.period, "score": dict(self.score), "teams": {}}
        for t in self.team_ids:
            tot = self.totals[t]
            snap["teams"][t] = {
                "passes": int(tot["passes"]),
                "pass_completion": tot["passes_complete"] / tot["passes"] if tot["passes"] else None,
                "shots": int(tot["shots"]),
                "turnovers_lost": int(tot["turnovers_lost"]),
                "pass_completion_5m": self.ratio(t, "passes_complete", "passes"),
                "long_ball_share_5m": self.ratio(t, "long_passes", "passes"),
            }
        for comp in self.components:
            extra = getattr(comp, "snapshot", None)
            if extra:
                snap.update(extra(self))
        return snap


def replay(meta: MatchMeta, events, components: list[Component] | None = None) -> tuple[MatchState, list[MetricUpdate]]:
    """Apply a whole event list; returns the final state and every update in order."""
    st = MatchState(meta, components)
    updates: list[MetricUpdate] = []
    for ev in events:
        updates.extend(st.apply(ev))
    return st, updates
