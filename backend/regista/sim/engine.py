"""Possession-chain match simulator.

Model summary
-------------
* 22 players hold continuous positions that relax towards a formation target
  (shifted with the ball) with time constant ~1.8 s. Out of possession, the
  k = 1 + round(2 * press) nearest defenders close the ball down to a distance
  that shrinks as pressing intensity rises. This is what makes pressure counts
  and pass difficulty emerge from geometry instead of being sampled directly.
* Each on-ball step picks pressure/tackle, shot, clearance, carry or pass.
* Pass completion is Bernoulli with
  logit p = 3.6 - 0.075 L - 0.55 n_passer - 0.35 n_receiver - 0.6 [high] + skill
  where L is pass length (m) and n_* are opponents within 5 m.
* Shot xG is logistic in distance, goal-mouth angle, header flag and
  defenders within 5 m. Organic shots never score; goals come only from the
  director's script, so the scoreline is deterministic while chance quality
  stays realistic.
* All randomness flows from one seeded ``random.Random``: same seed, same match.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterable

from ..contracts.events import (
    PERIOD_LENGTH_S,
    CarryEvent,
    ClearanceEvent,
    FoulEvent,
    FreezeFramePlayer,
    GroundTruth,
    InterceptionEvent,
    MatchFile,
    PassEvent,
    PeriodEndEvent,
    PeriodStartEvent,
    PossessionChangeEvent,
    Pressure,
    PressureEvent,
    SaveEvent,
    ShotEvent,
    SprintEvent,
    TackleEvent,
    TruthShot,
    attacks_right,
)
from ..contracts.events import (
    PITCH_LENGTH_M as L,
)
from ..contracts.events import (
    PITCH_WIDTH_M as W,
)
from .director import STOPPAGE_S, Director, ScriptedMoment
from .roster import AWAY_ID, FORMATION_433, HOME_ID, build_meta

GENERATOR = "regista-sim/0.1.0"

PASS_MODEL = {
    "intercept": 3.6,
    "length_per_m": -0.075,
    "passer_defenders_5m": -0.55,
    "receiver_defenders_5m": -0.35,
    "high": -0.6,
}
XG_MODEL = {
    "intercept": -0.9,
    "distance_per_m": -0.11,
    "angle_per_rad": 1.2,
    "header": -0.8,
    "defenders_5m": -0.35,
}

GOAL_X, GOAL_Y, POST_HALF = L, W / 2, 3.66


def sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def goal_geometry(xr: float, yr: float) -> tuple[float, float]:
    """Distance to goal centre and goal-mouth angle, in the attacking frame."""
    dist = math.hypot(GOAL_X - xr, GOAL_Y - yr)
    ax, ay = GOAL_X - xr, (GOAL_Y - POST_HALF) - yr
    bx, by = GOAL_X - xr, (GOAL_Y + POST_HALF) - yr
    angle = abs(math.atan2(ax * by - ay * bx, ax * bx + ay * by))
    return dist, angle


class MatchSimulator:
    def __init__(self, seed: int = 7, match_id: str = "RGS-2026-0001") -> None:
        self.rng = random.Random(seed)
        self.seed = seed
        self.meta = build_meta(match_id, seed, GENERATOR)
        self.director = Director()
        self.events: list = []
        self.truth_shots: list[TruthShot] = []
        self.scripted_ids: dict[str, str] = {}
        self.score = {HOME_ID: 0, AWAY_ID: 0}
        self.seq = 0

        self.team_of: dict[str, str] = {}
        self.role_of: dict[str, str] = {}
        self.by_role: dict[tuple[str, str], str] = {}
        for team in (self.meta.home, self.meta.away):
            for p in team.players:
                self.team_of[p.player_id] = team.team_id
                self.role_of[p.player_id] = p.role
                self.by_role[(team.team_id, p.role)] = p.player_id
        self.pos: dict[str, list[float]] = {pid: [L / 2, W / 2] for pid in self.team_of}

        self.period = 1
        self.t = 0.0
        self.p1_duration = 0.0
        self.poss_team = HOME_ID
        self.carrier: str = self.by_role[(HOME_ID, "ST")]
        self.ball = [L / 2, W / 2]
        self.possession_id = 0
        self.last_pass: PassEvent | None = None

    # ------------------------------------------------------------------ #
    # Frames, clock, geometry
    # ------------------------------------------------------------------ #
    @property
    def clock(self) -> float:
        return self.t if self.period == 1 else PERIOD_LENGTH_S + self.t

    def opp(self, team: str) -> str:
        return AWAY_ID if team == HOME_ID else HOME_ID

    def to_abs(self, team: str, xr: float, yr: float) -> tuple[float, float]:
        if attacks_right(self.meta, team, self.period):
            return xr, yr
        return L - xr, W - yr

    to_rel = to_abs  # the 180-degree rotation is its own inverse

    def players_of(self, team: str) -> list[str]:
        return [pid for pid, t in self.team_of.items() if t == team]

    def pressure_at(self, defending: str, x: float, y: float) -> Pressure:
        best_d, best_id, n5 = 1e9, None, 0
        for pid in self.players_of(defending):
            d = math.hypot(self.pos[pid][0] - x, self.pos[pid][1] - y)
            if d <= 5.0:
                n5 += 1
            if d < best_d:
                best_d, best_id = d, pid
        return Pressure(defenders_within_5m=n5, nearest_defender_m=round(best_d, 2), nearest_defender_id=best_id)

    def nearest(self, pids: Iterable[str], x: float, y: float) -> str:
        return min(pids, key=lambda pid: math.hypot(self.pos[pid][0] - x, self.pos[pid][1] - y))

    def place(self, pid: str, xr: float, yr: float) -> None:
        self.pos[pid] = list(self.to_abs(self.team_of[pid], xr, yr))

    # ------------------------------------------------------------------ #
    # Movement
    # ------------------------------------------------------------------ #
    def reset_shape(self) -> None:
        for pid, team in self.team_of.items():
            bx, by = FORMATION_433[self.role_of[pid]]
            self.pos[pid] = list(self.to_abs(team, bx * 0.48, by))

    def update_positions(self, dt: float) -> None:
        if dt <= 0:
            return
        a = 1.0 - math.exp(-dt / 1.8)
        a_press = 1.0 - math.exp(-dt / 0.9)
        rng = self.rng
        for team in (HOME_ID, AWAY_ID):
            in_poss = team == self.poss_team
            p = self.director.params(team, self.clock)
            bxr, byr = self.to_rel(team, *self.ball)
            targets: dict[str, tuple[float, float]] = {}
            for role, (fx, fy) in FORMATION_433.items():
                pid = self.by_role[(team, role)]
                if role == "GK":
                    tx = clamp(5.0 + 0.08 * max(0.0, bxr - 20.0), 2.0, 16.0)
                    ty = clamp(34.0 + 0.15 * (byr - 34.0), 28.0, 40.0)
                elif in_poss:
                    tx = clamp(fx + 0.55 * (bxr - 45.0) + 5.0, 3.0, 102.0)
                    ty = clamp(fy + 0.20 * (byr - 34.0), 2.0, 66.0)
                else:
                    tx = clamp(fx + 0.45 * (bxr - 45.0) - 3.0 + p.line_push_m, 3.0, 95.0)
                    ty = clamp(fy + 0.30 * (byr - 34.0), 2.0, 66.0)
                targets[pid] = self.to_abs(team, tx, ty)
            rates = {pid: a for pid in targets}
            if not in_poss:
                outfield = [pid for pid in targets if self.role_of[pid] != "GK"]
                outfield.sort(key=lambda pid: math.hypot(self.pos[pid][0] - self.ball[0], self.pos[pid][1] - self.ball[1]))
                k = 1 + int(round(2 * p.press))
                for i, pid in enumerate(outfield[:k]):
                    dx, dy = self.pos[pid][0] - self.ball[0], self.pos[pid][1] - self.ball[1]
                    n = math.hypot(dx, dy) or 1.0
                    d = max(1.2, 8.5 - 6.5 * p.press + 2.5 * i + rng.gauss(0, 1.0))
                    targets[pid] = (self.ball[0] + dx / n * d, self.ball[1] + dy / n * d)
                    rates[pid] = a_press
            for pid, (tx, ty) in targets.items():
                r = rates[pid]
                jitter = 0.6 * math.sqrt(r)
                self.pos[pid][0] = clamp(self.pos[pid][0] + r * (tx - self.pos[pid][0]) + rng.gauss(0, jitter), 0.5, L - 0.5)
                self.pos[pid][1] = clamp(self.pos[pid][1] + r * (ty - self.pos[pid][1]) + rng.gauss(0, jitter), 0.5, W - 0.5)
        self.pos[self.carrier] = list(self.ball)

    def advance(self, dt: float) -> None:
        self.t += dt
        # integrate long dead-ball gaps in chunks so pressers do not teleport
        remaining = dt
        while remaining > 0:
            step = min(remaining, 2.0)
            self.update_positions(step)
            remaining -= step

    # ------------------------------------------------------------------ #
    # Emission
    # ------------------------------------------------------------------ #
    def emit(self, cls, *, x: float, y: float, **kw):
        ev = cls(
            event_id=f"{self.meta.match_id}-{self.seq:05d}",
            seq=self.seq,
            match_id=self.meta.match_id,
            period=self.period,
            t=round(self.t, 2),
            match_clock_s=round(self.clock, 2),
            elapsed_s=round(self.p1_duration + self.t if self.period == 2 else self.t, 2),
            possession_id=self.possession_id,
            x=round(clamp(x, 0, L), 1),
            y=round(clamp(y, 0, W), 1),
            **kw,
        )
        self.events.append(ev)
        self.seq += 1
        return ev

    def change_possession(self, to_team: str, carrier: str, cause: str, x: float, y: float, from_team: str | None = "auto") -> None:
        frm = self.poss_team if from_team == "auto" else from_team
        self.possession_id += 1
        self.poss_team = to_team
        self.carrier = carrier
        self.ball = [clamp(x, 0.5, L - 0.5), clamp(y, 0.5, W - 0.5)]
        self.pos[carrier] = list(self.ball)
        self.emit(
            PossessionChangeEvent,
            x=x,
            y=y,
            team_id=to_team,
            player_id=carrier,
            from_team_id=frm,
            to_team_id=to_team,
            cause=cause,
        )

    # ------------------------------------------------------------------ #
    # Match flow
    # ------------------------------------------------------------------ #
    def run(self) -> tuple[MatchFile, GroundTruth]:
        for period, kickoff_team in ((1, HOME_ID), (2, AWAY_ID)):
            self.period = period
            self.t = 0.0
            self.emit(PeriodStartEvent, x=L / 2, y=W / 2)
            self.kickoff(kickoff_team, first=(period == 1))
            end_t = PERIOD_LENGTH_S + STOPPAGE_S[period]
            while self.t < end_t:
                moment = self.director.due(self.period, self.t)
                if moment:
                    self.play_scripted(moment)
                else:
                    self.step()
            self.emit(
                PeriodEndEvent,
                x=L / 2,
                y=W / 2,
                home_score=self.score[HOME_ID],
                away_score=self.score[AWAY_ID],
            )
            if period == 1:
                self.p1_duration = self.t
        match = MatchFile(meta=self.meta, events=self.events)
        truth = GroundTruth(
            match_id=self.meta.match_id,
            seed=self.seed,
            final_score=dict(self.score),
            storylines=Director.storylines(),
            scripted_event_ids=self.scripted_ids,
            shots=self.truth_shots,
            pass_model=PASS_MODEL,
            xg_model=XG_MODEL,
        )
        return match, truth

    def kickoff(self, team: str, first: bool = False) -> None:
        self.reset_shape()
        striker = self.by_role[(team, "ST")]
        self.change_possession(team, striker, "kickoff", L / 2, W / 2, from_team=None if first else self.poss_team)
        mid = self.by_role[(team, "CDM")]
        self.place(mid, 40.0, 34.0)
        self.do_pass(force_receiver=mid, force_complete=True)

    def step(self) -> None:
        rng = self.rng
        team, opp, c = self.poss_team, self.opp(self.poss_team), self.carrier
        p = self.director.params(team, self.clock)
        q = self.director.params(opp, self.clock)
        bxr, byr = self.to_rel(team, *self.ball)
        role = self.role_of[c]

        if role == "GK":
            self.do_pass()
            return

        pr = self.pressure_at(opp, *self.ball)
        if pr.nearest_defender_m <= 6.5 and rng.random() < 0.15 + 0.6 * q.press:
            presser = pr.nearest_defender_id
            self.emit(
                PressureEvent,
                x=self.pos[presser][0],
                y=self.pos[presser][1],
                team_id=opp,
                player_id=presser,
                target_player_id=c,
                distance_m=pr.nearest_defender_m,
                duration_s=round(rng.uniform(0.6, 2.0), 2),
            )
            self.advance(0.5)
            pr = self.pressure_at(opp, *self.ball)
            p_tackle = (0.10 + 0.25 * q.press) * (1.0 if pr.nearest_defender_m <= 3.0 else 0.35)
            if rng.random() < p_tackle:
                presser = pr.nearest_defender_id
                if rng.random() < 0.30:
                    card = "yellow" if rng.random() < 0.15 else None
                    self.emit(FoulEvent, x=self.ball[0], y=self.ball[1], team_id=opp, player_id=presser, fouled_player_id=c, card=card)
                    self.advance(rng.uniform(12, 25))
                    return
                self.emit(TackleEvent, x=self.ball[0], y=self.ball[1], team_id=opp, player_id=presser, opponent_id=c, outcome="won")
                self.change_possession(opp, presser, "tackle", *self.ball)
                self.advance(rng.uniform(0.6, 1.2))
                return

        dist, _ = goal_geometry(bxr, byr)
        if bxr >= 78 and dist <= 28:
            if rng.random() < sigmoid(-(dist - 14.0) / 4.0) * 0.32 * p.shot_appetite:
                self.do_shot()
                return

        if self.role_of[c] in ("RB", "RCB", "LCB", "LB") and bxr < 25 and pr.defenders_within_5m >= 1 and rng.random() < 0.25:
            self.do_clearance()
            return

        if rng.random() < (0.22 if pr.nearest_defender_m > 5 else 0.10):
            self.do_carry()
            return
        self.do_pass()

    # ------------------------------------------------------------------ #
    # Actions
    # ------------------------------------------------------------------ #
    def do_carry(self, length: float | None = None, end_rel: tuple[float, float] | None = None, top_speed: float | None = None) -> None:
        rng, team, c = self.rng, self.poss_team, self.carrier
        bxr, byr = self.to_rel(team, *self.ball)
        if end_rel is None:
            space = self.pressure_at(self.opp(team), *self.ball).nearest_defender_m
            length = length or rng.uniform(3.0, 6.0 + min(space, 15.0) * 0.6)
            theta = rng.gauss(0.0, 0.6)
            if bxr > 85:
                theta = math.atan2(34.0 - byr, max(1.0, 100.0 - bxr)) + rng.gauss(0, 0.3)
            ex = clamp(bxr + length * math.cos(theta), 1.0, 104.0)
            ey = clamp(byr + length * math.sin(theta), 1.0, 67.0)
        else:
            ex, ey = end_rel
        dist = math.hypot(ex - bxr, ey - byr)
        if top_speed is None:
            mean_kmh = rng.uniform(13.0, 22.0)
            top = mean_kmh * rng.uniform(1.05, 1.25)
        else:
            top = top_speed
            mean_kmh = top * 0.86
        dur = max(0.3, dist / (mean_kmh / 3.6))
        ax, ay = self.to_abs(team, ex, ey)
        self.emit(
            CarryEvent,
            x=self.ball[0],
            y=self.ball[1],
            team_id=team,
            player_id=c,
            end_x=round(ax, 1),
            end_y=round(ay, 1),
            distance_m=round(dist, 2),
            duration_s=round(dur, 2),
            top_speed_kmh=round(top, 1),
        )
        start = list(self.ball)
        self.ball = [ax, ay]
        self.advance(dur)
        if top >= 25.0:
            self.emit(
                SprintEvent,
                x=start[0],
                y=start[1],
                team_id=team,
                player_id=c,
                top_speed_kmh=round(top, 1),
                distance_m=round(dist * rng.uniform(1.05, 1.3), 1),
                duration_s=round(dur * rng.uniform(1.05, 1.3), 2),
            )

    def _choose_receiver(self, long: bool) -> str:
        rng, team, c = self.rng, self.poss_team, self.carrier
        p = self.director.params(team, self.clock)
        bxr, byr = self.to_rel(team, *self.ball)
        opp = self.opp(team)
        cands, weights = [], []
        for pid in self.players_of(team):
            if pid == c:
                continue
            rx, ry = self.to_rel(team, *self.pos[pid])
            d = math.hypot(rx - bxr, ry - byr)
            fwd = rx - bxr
            openness = self.pressure_at(opp, *self.pos[pid]).nearest_defender_m
            if long:
                w = (max(0.0, fwd) ** 1.2) * (1.0 if d > 25 else 0.1) + 1e-3
            else:
                w = math.exp(-(((d - 15.0) / 11.0) ** 2)) * math.exp(0.035 * fwd * p.directness) * (0.3 + min(openness, 8.0) / 8.0)
            if self.role_of[pid] == "GK":
                w *= 0.15
            cands.append(pid)
            weights.append(w)
        return rng.choices(cands, weights=weights, k=1)[0]

    def do_pass(
        self,
        force_receiver: str | None = None,
        force_complete: bool | None = None,
        end_rel: tuple[float, float] | None = None,
        height: str | None = None,
        through: bool = False,
        cross: bool = False,
    ) -> PassEvent:
        rng, team, c = self.rng, self.poss_team, self.carrier
        opp = self.opp(team)
        p = self.director.params(team, self.clock)
        bxr, byr = self.to_rel(team, *self.ball)
        is_gk = self.role_of[c] == "GK"
        long = rng.random() < (0.45 if is_gk else p.long_ball) and force_receiver is None
        receiver = force_receiver or self._choose_receiver(long)

        if end_rel is not None:
            ex, ey = self.to_abs(team, *end_rel)
        else:
            d0 = math.hypot(self.pos[receiver][0] - self.ball[0], self.pos[receiver][1] - self.ball[1])
            sd = 0.8 + 0.04 * d0
            ex = clamp(self.pos[receiver][0] + rng.gauss(0, sd), 0.5, L - 0.5)
            ey = clamp(self.pos[receiver][1] + rng.gauss(0, sd), 0.5, W - 0.5)
        length = math.hypot(ex - self.ball[0], ey - self.ball[1])
        rxr, ryr = self.to_rel(team, ex, ey)

        if not cross and force_receiver is None and bxr > 75 and abs(byr - 34) > 16 and rxr > 88 and abs(ryr - 34) < 12:
            cross = True
        if height is None:
            if cross or long or length > 32:
                height = "high" if rng.random() < 0.85 else "low"
            elif length > 20 and rng.random() < 0.3:
                height = "low"
            else:
                height = "ground"
        if not through and not cross and force_receiver is None:
            through = (rxr - bxr) > 12 and self.role_of[receiver] in ("ST", "RW", "LW") and rng.random() < 0.3

        pr = self.pressure_at(opp, *self.ball)
        n_recv = self.pressure_at(opp, ex, ey).defenders_within_5m
        logit = (
            PASS_MODEL["intercept"]
            + PASS_MODEL["length_per_m"] * length
            + PASS_MODEL["passer_defenders_5m"] * pr.defenders_within_5m
            + PASS_MODEL["receiver_defenders_5m"] * n_recv
            + PASS_MODEL["high"] * (height == "high")
            + p.pass_skill
        )
        ok = force_complete if force_complete is not None else rng.random() < sigmoid(logit)
        outcome = "complete"
        if not ok:
            near_touch = min(ey, W - ey) < 8 or long
            outcome = "out" if rng.random() < (0.45 if near_touch else 0.15) else "incomplete"
        if outcome == "out":
            if min(ey, W - ey) <= min(ex, L - ex):
                ey = 0.0 if ey < W / 2 else W
            else:
                ex = 0.0 if ex < L / 2 else L
            length = math.hypot(ex - self.ball[0], ey - self.ball[1])

        v = {"ground": rng.uniform(11.0, 16.0), "low": rng.uniform(14.0, 19.0), "high": rng.uniform(15.0, 21.0)}[height]
        duration = max(0.25, length / v + (0.35 if height == "high" else 0.0))
        ev = self.emit(
            PassEvent,
            x=self.ball[0],
            y=self.ball[1],
            team_id=team,
            player_id=c,
            end_x=round(ex, 1),
            end_y=round(ey, 1),
            recipient_id=receiver if outcome == "complete" else None,
            outcome=outcome,
            length_m=round(length, 2),
            height=height,
            duration_s=round(duration, 2),
            ball_speed_kmh=round(length / duration * 3.6, 1),
            pressure=pr,
            receiver_defenders_within_5m=n_recv,
            is_cross=cross,
            is_through_ball=through,
        )
        self.advance(duration)

        if outcome == "complete":
            self.last_pass = ev
            self.carrier = receiver
            self.ball = [ex, ey]
            self.pos[receiver] = [ex, ey]
            self.advance(rng.uniform(0.5, 2.0) * p.tempo)
        elif outcome == "incomplete":
            self.last_pass = None
            interceptor = self.nearest(self.players_of(opp), ex, ey)
            self.emit(InterceptionEvent, x=ex, y=ey, team_id=opp, player_id=interceptor, pass_event_id=ev.event_id)
            self.change_possession(opp, interceptor, "interception", ex, ey)
            self.advance(rng.uniform(0.5, 1.5))
        else:
            self.last_pass = None
            over_goal_line = ex in (0.0, L)
            attacking_line = over_goal_line and self.to_rel(team, ex, ey)[0] > L / 2
            if attacking_line:
                gk = self.by_role[(opp, "GK")]
                gx, gy = self.to_abs(opp, 5.5, 34.0)
                self.advance(rng.uniform(18, 30))
                self.change_possession(opp, gk, "goal_kick", gx, gy)
            else:
                taker = self.nearest([pid for pid in self.players_of(opp) if self.role_of[pid] != "GK"], ex, ey)
                self.advance(rng.uniform(8, 20))
                self.change_possession(opp, taker, "out_of_play", ex, ey)
        return ev

    def do_clearance(self) -> None:
        rng, team, c = self.rng, self.poss_team, self.carrier
        opp = self.opp(team)
        lx, ly = rng.uniform(55, 80), rng.uniform(8, 60)
        ax, ay = self.to_abs(team, lx, ly)
        self.emit(ClearanceEvent, x=self.ball[0], y=self.ball[1], team_id=team, player_id=c, end_x=round(ax, 1), end_y=round(ay, 1))
        self.advance(rng.uniform(2.0, 3.5))
        winner_team = team if rng.random() < 0.45 else opp
        winner = self.nearest(self.players_of(winner_team), ax, ay)
        if winner_team == team:
            self.carrier = winner
            self.ball = [ax, ay]
            self.pos[winner] = [ax, ay]
        else:
            self.change_possession(opp, winner, "clearance", ax, ay)

    def _freeze_frame(self) -> list[FreezeFramePlayer]:
        return [FreezeFramePlayer(player_id=pid, x=round(xy[0], 1), y=round(xy[1], 1)) for pid, xy in self.pos.items()]

    def clear_space(self, team_def: str, radius: float) -> None:
        """Push outfield defenders to ``radius`` m from the ball (scripted chances only)."""
        for pid in self.players_of(team_def):
            if self.role_of[pid] == "GK":
                continue
            dx, dy = self.pos[pid][0] - self.ball[0], self.pos[pid][1] - self.ball[1]
            d = math.hypot(dx, dy)
            if d < radius:
                n = d or 1.0
                self.pos[pid] = [clamp(self.ball[0] + dx / n * radius, 0.5, L - 0.5), clamp(self.ball[1] + dy / n * radius, 0.5, W - 0.5)]

    def do_shot(self, scripted_goal: str | None = None, body: str | None = None) -> ShotEvent:
        rng, team, c = self.rng, self.poss_team, self.carrier
        opp = self.opp(team)
        if scripted_goal:
            self.clear_space(opp, 5.5)
        bxr, byr = self.to_rel(team, *self.ball)
        dist, ang = goal_geometry(bxr, byr)
        pr = self.pressure_at(opp, *self.ball)
        lp = self.last_pass
        assisted = lp is not None and lp.recipient_id == c and lp.team_id == team
        if body is None:
            if assisted and lp.height == "high" and rng.random() < 0.7:
                body = "head"
            else:
                body = "right_foot" if rng.random() < 0.7 else "left_foot"
        is_head = body == "head"
        xg = sigmoid(
            XG_MODEL["intercept"]
            + XG_MODEL["distance_per_m"] * dist
            + XG_MODEL["angle_per_rad"] * ang
            + XG_MODEL["header"] * is_head
            + XG_MODEL["defenders_5m"] * pr.defenders_within_5m
        )
        if scripted_goal:
            outcome = "goal"
        else:
            u = rng.random()
            if u < 0.12 + 0.12 * pr.defenders_within_5m:
                outcome = "blocked"
            elif rng.random() < 0.42:
                outcome = "saved"
            elif rng.random() < 0.04:
                outcome = "woodwork"
            else:
                outcome = "off_target"
        speed = rng.gauss(55, 8) if is_head else rng.gauss(88, 14) - 0.4 * max(0.0, dist - 16.0)
        ev = self.emit(
            ShotEvent,
            x=self.ball[0],
            y=self.ball[1],
            team_id=team,
            player_id=c,
            outcome=outcome,
            body_part=body,
            shot_speed_kmh=round(clamp(speed, 35.0, 125.0), 1),
            distance_m=round(dist, 2),
            angle_rad=round(ang, 4),
            pressure=pr,
            assist_event_id=lp.event_id if assisted else None,
            freeze_frame=self._freeze_frame(),
        )
        self.truth_shots.append(TruthShot(event_id=ev.event_id, xg_true=round(xg, 4)))
        self.last_pass = None
        self.advance(0.8)
        gk = self.by_role[(opp, "GK")]
        if outcome == "goal":
            self.score[team] += 1
            if scripted_goal:
                self.scripted_ids[scripted_goal] = ev.event_id
            self.advance(rng.uniform(45, 70))
            self.kickoff(opp)
        elif outcome == "saved":
            self.emit(SaveEvent, x=self.pos[gk][0], y=self.pos[gk][1], team_id=opp, player_id=gk, shot_event_id=ev.event_id)
            self.advance(rng.uniform(2.0, 5.0))
            self.change_possession(opp, gk, "save", *self.pos[gk])
        elif outcome == "blocked":
            if rng.random() < 0.5:
                rx, ry = self.to_rel(team, *self.ball)
                lx, ly = clamp(rx - rng.uniform(4, 12), 60, 100), clamp(ry + rng.gauss(0, 8), 5, 63)
                ax, ay = self.to_abs(team, lx, ly)
                winner = self.nearest(self.players_of(team), ax, ay)
                self.carrier, self.ball = winner, [ax, ay]
                self.pos[winner] = [ax, ay]
                self.advance(1.0)
            else:
                blocker = pr.nearest_defender_id
                ox, oy = self.to_abs(opp, rng.uniform(45, 70), rng.uniform(8, 60))
                self.emit(
                    ClearanceEvent, x=self.ball[0], y=self.ball[1], team_id=opp, player_id=blocker, end_x=round(ox, 1), end_y=round(oy, 1)
                )
                self.advance(2.5)
                winner = self.nearest(self.players_of(opp), ox, oy)
                self.change_possession(opp, winner, "clearance", ox, oy)
        else:
            gx, gy = self.to_abs(opp, 5.5, 34.0)
            self.advance(rng.uniform(20, 32))
            self.change_possession(opp, gk, "goal_kick", gx, gy)
        return ev

    # ------------------------------------------------------------------ #
    # Scripted moments
    # ------------------------------------------------------------------ #
    def pid(self, team: str, role: str) -> str:
        return self.by_role[(team, role)]

    def ensure_possession(self, team: str, receiver: str, at_rel: tuple[float, float]) -> None:
        """Get the ball to ``receiver`` at ``at_rel`` (team frame) with a coherent event trail."""
        self.place(receiver, *at_rel)
        if self.poss_team == team:
            if self.carrier != receiver:
                self.do_pass(force_receiver=receiver, force_complete=True, end_rel=at_rel, height="ground")
            return
        # opponent has the ball: their next pass is read and intercepted by `receiver`
        target = self.to_rel(self.poss_team, *self.pos[receiver])
        ev = self.emit(
            PassEvent,
            x=self.ball[0],
            y=self.ball[1],
            team_id=self.poss_team,
            player_id=self.carrier,
            end_x=round(self.pos[receiver][0], 1),
            end_y=round(self.pos[receiver][1], 1),
            recipient_id=None,
            outcome="incomplete",
            length_m=round(math.hypot(self.pos[receiver][0] - self.ball[0], self.pos[receiver][1] - self.ball[1]), 2),
            height="ground",
            duration_s=0.9,
            ball_speed_kmh=round(math.hypot(self.pos[receiver][0] - self.ball[0], self.pos[receiver][1] - self.ball[1]) / 0.9 * 3.6, 1),
            pressure=self.pressure_at(team, *self.ball),
            receiver_defenders_within_5m=self.pressure_at(team, *self.to_abs(self.poss_team, *target)).defenders_within_5m,
        )
        self.advance(0.9)
        self.emit(
            InterceptionEvent, x=self.pos[receiver][0], y=self.pos[receiver][1], team_id=team, player_id=receiver, pass_event_id=ev.event_id
        )
        self.change_possession(team, receiver, "interception", *self.pos[receiver])
        self.advance(0.8)

    def press_on(self, presser: str, target: str, gap_m: float) -> None:
        tx, ty = self.pos[target]
        self.pos[presser] = [clamp(tx + gap_m * 0.8, 0.5, L - 0.5), clamp(ty + gap_m * 0.6, 0.5, W - 0.5)]
        self.emit(
            PressureEvent,
            x=self.pos[presser][0],
            y=self.pos[presser][1],
            team_id=self.team_of[presser],
            player_id=presser,
            target_player_id=target,
            distance_m=round(gap_m, 2),
            duration_s=1.4,
        )
        self.advance(0.5)

    def play_scripted(self, m: ScriptedMoment) -> None:
        H, A = HOME_ID, AWAY_ID
        if m.kind == "goal_home_through_ball":
            self.ensure_possession(H, self.pid(H, "CDM"), (52.0, 33.0))
            self.place(self.pid(H, "LCM"), 58.0, 44.0)
            self.do_pass(force_receiver=self.pid(H, "LCM"), force_complete=True, end_rel=(58.0, 44.0), height="ground")
            self.do_carry(end_rel=(67.0, 40.0), top_speed=21.5)
            self.place(self.pid(H, "ST"), 90.0, 32.0)
            self.do_pass(force_receiver=self.pid(H, "ST"), force_complete=True, end_rel=(94.5, 33.0), height="ground", through=True)
            self.do_shot(scripted_goal=m.moment_id, body="right_foot")

        elif m.kind == "goal_away_high_press":
            if self.poss_team == A:
                self.do_pass(force_complete=False)  # may end in any turnover; loop until home have it
                while self.poss_team == A:
                    self.do_pass(force_complete=False)
            gk, rcb, cdm = self.pid(H, "GK"), self.pid(H, "RCB"), self.pid(H, "CDM")
            if self.carrier != gk:
                self.place(gk, 6.0, 34.0)
                self.do_pass(force_receiver=gk, force_complete=True, end_rel=(6.0, 34.0), height="ground")
            self.place(rcb, 15.0, 22.0)
            self.do_pass(force_receiver=rcb, force_complete=True, end_rel=(15.0, 22.0), height="ground")
            self.press_on(self.pid(A, "ST"), rcb, 2.6)
            self.press_on(self.pid(A, "RW"), rcb, 4.2)
            self.place(cdm, 27.0, 29.0)
            self.do_pass(force_receiver=cdm, force_complete=True, end_rel=(27.0, 29.0), height="ground")
            lindqvist = self.pid(A, "CDM")
            self.press_on(lindqvist, cdm, 1.6)
            self.emit(TackleEvent, x=self.ball[0], y=self.ball[1], team_id=A, player_id=lindqvist, opponent_id=cdm, outcome="won")
            self.change_possession(A, lindqvist, "tackle", *self.ball)
            self.advance(0.7)
            self.place(self.pid(A, "ST"), 91.0, 35.0)
            self.do_pass(force_receiver=self.pid(A, "ST"), force_complete=True, end_rel=(92.5, 35.5), height="ground")
            self.do_shot(scripted_goal=m.moment_id, body="left_foot")

        elif m.kind == "sprint_counter":
            self.ensure_possession(A, self.pid(A, "LCM"), (40.0, 40.0))
            balogun = self.pid(A, "LW")
            self.place(balogun, 48.0, 58.0)
            self.do_pass(force_receiver=balogun, force_complete=True, end_rel=(48.0, 58.0), height="low")
            start_seq = self.seq
            self.do_carry(end_rel=(86.0, 55.0), top_speed=34.8)
            sprint = next(e for e in self.events[start_seq:] if e.type == "sprint")
            self.scripted_ids[m.moment_id] = sprint.event_id
            self.do_pass(force_receiver=self.pid(A, "ST"), force_complete=False, end_rel=(97.0, 36.0), height="high", cross=True)

        elif m.kind == "goal_home_header":
            self.ensure_possession(H, self.pid(H, "RCM"), (60.0, 22.0))
            haddad = self.pid(H, "RW")
            self.place(haddad, 70.0, 10.0)
            self.do_pass(force_receiver=haddad, force_complete=True, end_rel=(70.0, 10.0), height="ground")
            self.do_carry(end_rel=(88.0, 8.0), top_speed=27.4)
            self.place(self.pid(H, "ST"), 95.0, 32.0)
            self.do_pass(force_receiver=self.pid(H, "ST"), force_complete=True, end_rel=(96.0, 32.5), height="high", cross=True)
            self.do_shot(scripted_goal=m.moment_id, body="head")


def simulate(seed: int = 7, match_id: str = "RGS-2026-0001") -> tuple[MatchFile, GroundTruth]:
    return MatchSimulator(seed=seed, match_id=match_id).run()
