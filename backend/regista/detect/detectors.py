"""Moment detectors. Each turns state into a ``Draft`` with facts and evidence.

Numbers in facts are rounded for display here, once, so every downstream
rendering and the Verifier see the same value.
"""

from __future__ import annotations

from ..contracts.events import format_clock
from ..state import ControlChaos, MatchState, MetricUpdate, Momentum, Press, Records
from ..state.core import TURNOVER_CAUSES
from .base import Detector, Draft, FactDraft, event_ref, metric_ref, pct

BODY_PART = {"head": "header", "right_foot": "right foot", "left_foot": "left foot"}
SHOT_OUTCOME = {"saved": "saved", "off_target": "off target", "blocked": "blocked", "woodwork": "hit the woodwork", "goal": "goal"}


def _name(st: MatchState, pid: str) -> str:
    return st.players[pid].short_name


def _team_name(st: MatchState, team_id: str) -> str:
    return st.meta.home.name if team_id == st.home_id else st.meta.away.name


def _has(updates: list[MetricUpdate], key: str) -> bool:
    return any(u.key == key for u in updates)


def _clock_at(st: MatchState, elapsed_s: float) -> str:
    return format_clock(st.period, max(0.0, elapsed_s - st.period_start_s))


class GoalDetector(Detector):
    """Every goal: scorer, score, chance quality, assist and, when the ball was won in open play, the turnover chain."""

    kind = "goal"
    turnover_link_s = 20.0
    press_link_s = 600.0

    def detect(self, ev, updates, st):
        """A goal insight on each goal."""
        if ev.type != "shot" or ev.outcome != "goal":
            return []
        team, opp, pid = ev.team_id, st.opp(ev.team_id), ev.player_id
        shot = [event_ref(ev.event_id)]
        all_goals = sorted(e for ids in st.goal_events.values() for e in ids)
        h, a = st.score[st.home_id], st.score[st.away_id]
        facts = [
            FactDraft("goal.scorer", "Scorer", _name(st, pid), shot),
            FactDraft("match.score", f"Score ({st.home_id}-{st.away_id})", f"{h}-{a}", [event_ref(e) for e in all_goals]),
            FactDraft("shot.xg", "Chance quality", round(st.shot_xg.get(ev.event_id, 0.0), 2), shot, "xG"),
            FactDraft("shot.distance_m", "Shot distance", round(ev.distance_m, 1), shot, "m"),
            FactDraft("shot.body_part", "Finish", BODY_PART[ev.body_part], shot),
            FactDraft(
                f"{pid}.match_goals",
                f"{_name(st, pid)} goals this match",
                st.player_goals[pid],
                [event_ref(e) for e in st.goal_events[pid]],
            ),
        ]
        players = [pid]
        hint = f"{_name(st, pid)} scores for {_team_name(st, team)} ({h}-{a})."
        assist = st.passes.get(ev.assist_event_id) if ev.assist_event_id else None
        if assist is not None:
            players.append(assist.player_id)
            facts.append(FactDraft("goal.assist", "Assist", _name(st, assist.player_id), [event_ref(assist.event_id)]))
            kind = "through ball" if assist.is_through_ball else "cross" if assist.is_cross else None
            if kind:
                facts.append(FactDraft("assist.type", "Assist type", kind, [event_ref(assist.event_id)]))
                hint += f" Created by a {kind} from {_name(st, assist.player_id)}."
        ps = st.poss_start
        if (
            ps is not None
            and ps.cause in TURNOVER_CAUSES
            and ps.from_team_id == opp
            and ev.elapsed_s - ps.elapsed_s <= self.turnover_link_s
        ):
            players.append(ps.player_id)
            won = [event_ref(ps.event_id)]
            facts += [
                FactDraft("goal.won_ball_by", "Won the ball", _name(st, ps.player_id), won),
                FactDraft("goal.seconds_from_turnover", "Turnover to goal", round(ev.elapsed_s - ps.elapsed_s), [*won, *shot], "s"),
                FactDraft("goal.turnover_distance_to_goal_m", "Ball won from goal", round(105.0 - st.rel_x(team, ps.x)), won, "m"),
            ]
            hint += f" {_name(st, ps.player_id)} won it back {round(ev.elapsed_s - ps.elapsed_s)} s earlier."
            press = st.component(Press)
            alarm = next((al for al in reversed(press.alarms) if al.team_id == team), None) if press else None
            if alarm is not None and st.now - alarm.elapsed_s <= self.press_link_s:
                n = st.window(opp, "passes")
                share = st.window(opp, "pressed_passes") / n if n else 0.0
                facts.append(
                    FactDraft(
                        f"{team}.pressed_pass_share_5m",
                        f"{_team_name(st, opp)} passes under pressure",
                        pct(share),
                        [metric_ref(f"{team}.pressed_pass_share_5m", *st.window_bounds("5m"))],
                        "%",
                        pct(alarm.baseline_pressed_share),
                    )
                )
                hint += " The goal comes out of their high press."
        return [Draft("goal", 5, 12000, facts, hint, f"goal:{ev.event_id}", team, [team], players)]


class ShotQualityDetector(Detector):
    """Big chances that were not scored (xG at least 0.25)."""

    kind = "shot_quality"
    cooldown_s = 120.0
    min_xg = 0.25

    def detect(self, ev, updates, st):
        """A chance insight for a big chance."""
        if ev.type != "shot" or ev.outcome == "goal":
            return []
        xg = st.shot_xg.get(ev.event_id, 0.0)
        if xg < self.min_xg:
            return []
        shot, team = [event_ref(ev.event_id)], ev.team_id
        facts = [
            FactDraft("shot.player", "Shooter", _name(st, ev.player_id), shot),
            FactDraft("shot.xg", "Chance quality", round(xg, 2), shot, "xG"),
            FactDraft("shot.distance_m", "Shot distance", round(ev.distance_m, 1), shot, "m"),
            FactDraft("shot.outcome", "Outcome", SHOT_OUTCOME[ev.outcome], shot),
            FactDraft(
                f"{team}.xg_total",
                f"{_team_name(st, team)} xG",
                round(st.totals[team]["xg"], 2),
                [metric_ref(f"{team}.xg_total", 0.0, st.now)],
                "xG",
            ),
        ]
        hint = f"Big chance for {_name(st, ev.player_id)} ({xg:.2f} xG), {SHOT_OUTCOME[ev.outcome]}."
        return [Draft("shot_quality", 3, 8000, facts, hint, f"shot:{ev.event_id}", team, [team], [ev.player_id])]


class KeyPassDetector(Detector):
    """The pass behind a shot, when it was a through ball, hard, a cross for a big chance, or an assist."""

    kind = "key_pass"
    cooldown_s = 120.0
    min_difficulty = 0.4
    min_xg = 0.15
    min_cross_xg = 0.3

    def detect(self, ev, updates, st):
        """A key-pass insight when a shot follows a notable pass."""
        if ev.type != "shot" or not ev.assist_event_id:
            return []
        p = st.passes.get(ev.assist_event_id)
        if p is None:
            return []
        difficulty = 1.0 - st.pass_p.get(p.event_id, 1.0)
        xg = st.shot_xg.get(ev.event_id, 0.0)
        kind = "through ball" if p.is_through_ball else "cross" if p.is_cross else "pass"
        notable = ev.outcome == "goal" or (
            xg >= self.min_xg
            and (kind == "through ball" or difficulty >= self.min_difficulty or (kind == "cross" and xg >= self.min_cross_xg))
        )
        if not notable:
            return []
        pref, shot = [event_ref(p.event_id)], [event_ref(ev.event_id)]
        facts = [
            FactDraft("pass.player", "Passer", _name(st, p.player_id), pref),
            FactDraft("pass.type", "Pass type", kind, pref),
            FactDraft("pass.difficulty", "Pass difficulty", pct(difficulty), pref, "%"),
            FactDraft("pass.length_m", "Pass length", round(p.length_m, 1), pref, "m"),
            FactDraft("pass.receiver", "Found", _name(st, ev.player_id), shot),
            FactDraft("shot.xg", "Chance created", round(xg, 2), shot, "xG"),
            FactDraft("shot.outcome", "Outcome", SHOT_OUTCOME[ev.outcome], shot),
        ]
        hint = (
            f"{_name(st, p.player_id)}'s {kind} ({pct(difficulty)}% difficulty) set up a {xg:.2f} xG chance for {_name(st, ev.player_id)}."
        )
        priority = 4 if ev.outcome == "goal" else 3
        return [
            Draft("key_pass", priority, 8000, facts, hint, f"key_pass:{p.event_id}", p.team_id, [p.team_id], [p.player_id, ev.player_id])
        ]


class MomentumShiftDetector(Detector):
    """Fires when a different team becomes dominant: |index| >= 0.4, released below 0.1 (hysteresis)."""

    kind = "momentum_shift"
    cooldown_s = 300.0
    enter, release = 0.4, 0.1
    min_total = 15.0
    warmup_s = 360.0

    def __init__(self) -> None:
        self.regime: str | None = None
        self.announced: str | None = None
        self.shares_at_announce: dict[str, int] = {}  # both teams' shares at the previous shift
        self._pending: dict[str, int] = {}

    def detect(self, ev, updates, st):
        """A momentum insight when a different team becomes dominant."""
        if ev.type == "period_start":
            self.regime = None
        if not _has(updates, "match.momentum_index"):
            return []
        mom = st.component(Momentum)
        h, a = mom.value(st.home_id, st.now), mom.value(st.away_id, st.now)
        if st.now - st.period_start_s < self.warmup_s or h + a < self.min_total:
            return []
        idx = mom.index(st)
        if abs(idx) < self.release:
            self.regime = None
        if idx >= self.enter:
            self.regime = st.home_id
        elif idx <= -self.enter:
            self.regime = st.away_id
        team = self.regime
        if team is None or team == self.announced:
            return []
        share = pct(mom.share(team, st))
        lo = max(st.period_start_s, st.now - 2 * mom.half_life_s)
        refs = [metric_ref(f"{team}.momentum", lo, st.now), *(event_ref(e) for e in mom.top_contributors(team, st.now))]
        facts = [
            FactDraft(
                f"{team}.momentum_share", f"{_team_name(st, team)} share of momentum", share, refs, "%", self.shares_at_announce.get(team)
            ),
            FactDraft(
                f"{team}.final_third_passes_5m",
                f"{_team_name(st, team)} completed passes into the final third (5 min)",
                int(st.window(team, "passes_final_third")),
                [metric_ref(f"{team}.passes_final_third", *st.window_bounds("5m"))],
            ),
            FactDraft(
                f"{team}.xg_10m",
                f"{_team_name(st, team)} xG (10 min)",
                round(st.window(team, "xg", "10m"), 2),
                [metric_ref(f"{team}.xg_10m", *st.window_bounds("10m"))],
                "xG",
            ),
        ]
        hint = f"Momentum swings to {_team_name(st, team)}: {share}% of attacking threat over the last few minutes."
        self._pending = {t: pct(mom.share(t, st)) for t in st.team_ids}
        return [Draft("momentum_shift", 3, 10000, facts, hint, f"momentum:{team}:{ev.event_id}", "match", [team], [])]

    def admitted(self, draft: Draft) -> None:
        """Remember the announced team and both teams' shares at that moment."""
        self.announced = draft.team_ids[0]
        self.shares_at_announce = self._pending


class PressChangeDetector(Detector):
    """One insight per press spell: after firing, a team re-arms only when its pressed-pass share
    (5 min) falls back to within 0.15 of the half's baseline, or at the next period."""

    kind = "press_change"
    cooldown_s = 600.0
    rearm_margin = 0.15

    def __init__(self) -> None:
        self.active: dict[str, float] = {}  # team -> baseline pressed share of the announced spell
        self._baseline: dict[str, float] = {}

    def detect(self, ev, updates, st):
        """A press insight on a confirmed CUSUM alarm, unless that team's spell is already announced."""
        if ev.type == "period_start":
            self.active.clear()
        for team, base in list(self.active.items()):
            n = st.window(st.opp(team), "passes")
            if n >= 10 and st.window(st.opp(team), "pressed_passes") / n < base + self.rearm_margin:
                del self.active[team]
        alarm_keys = [u for u in updates if u.key.endswith(".press_alarm")]
        if not alarm_keys:
            return []
        press = st.component(Press)
        out = []
        for u in alarm_keys:
            team = u.key.split(".")[0]
            if team in self.active:
                continue
            alarm = next(al for al in reversed(press.alarms) if al.team_id == team)
            opp = st.opp(team)
            change = metric_ref(f"{team}.press_cusum", alarm.change_start_s, st.now)
            baseline = metric_ref(f"{team}.press_baseline", st.period_start_s, min(st.now, st.period_start_s + 1200.0))
            facts = [
                FactDraft(
                    f"{team}.pressed_pass_share_5m",
                    f"{_team_name(st, opp)} passes under pressure",
                    pct(alarm.recent_pressed_share),
                    [metric_ref(f"{team}.pressed_pass_share_5m", *st.window_bounds("5m")), baseline],
                    "%",
                    pct(alarm.baseline_pressed_share),
                ),
                FactDraft(
                    f"{team}.pressures_per_opp_pass_5m",
                    f"{_team_name(st, team)} pressures per {_team_name(st, opp)} pass",
                    round(alarm.pressures_per_pass_5m, 2),
                    [
                        metric_ref(f"{team}.pressures_per_opp_pass_5m", *st.window_bounds("5m")),
                        baseline,
                        *map(event_ref, alarm.pressure_event_ids),
                    ],
                    None,
                    round(alarm.baseline_pressures_per_pass, 2),
                ),
                FactDraft(
                    f"{opp}.pass_completion_5m",
                    f"{_team_name(st, opp)} pass completion (5 min)",
                    pct(st.ratio(opp, "passes_complete", "passes") or 0.0),
                    [metric_ref(f"{opp}.pass_completion_5m", *st.window_bounds("5m"))],
                    "%",
                ),
                FactDraft(f"{team}.press_change_start", "Press change began", _clock_at(st, alarm.change_start_s), [change]),
            ]
            hint = (
                f"{_team_name(st, team)} have stepped up their press: {pct(alarm.recent_pressed_share)}% of "
                f"{_team_name(st, opp)} passes under pressure vs {pct(alarm.baseline_pressed_share)}% earlier in the half."
            )
            out.append(Draft("press_change", 4, 10000, facts, hint, f"press:{team}:{ev.event_id}", team, [team], []))
            self._baseline[team] = alarm.baseline_pressed_share
        return out

    def admitted(self, draft: Draft) -> None:
        """Mark the team's press spell as announced."""
        team = draft.team_ids[0]
        self.active[team] = self._baseline[team]


class ControlChaosDetector(Detector):
    """Regimes on the match chaos index: chaos >= 0.70 (held while >= 0.60), control <= 0.45 (held while <= 0.55).

    "Control" also needs a dominant side: control score >= 0.6, at least 0.1 above the opponent's,
    and at least 55% of the passes in the window. Otherwise the game is balanced and nothing fires.
    """

    kind = "control_vs_chaos"
    cooldown_s = 300.0
    chaos_enter, chaos_hold = 0.70, 0.60
    control_enter, control_hold = 0.45, 0.55
    warmup_s = 300.0
    min_control, min_control_margin, min_pass_share = 0.6, 0.1, 0.55

    def __init__(self) -> None:
        self.regime: tuple[str, str | None] | None = None
        self.announced: tuple[str, str | None] | None = None
        self.chaos_at_announce: float | None = None

    def detect(self, ev, updates, st):
        """An insight when the match enters a chaos regime or one side takes control."""
        if not _has(updates, "match.chaos_5m") or st.now - st.period_start_s < self.warmup_s:
            return []
        cc = st.component(ControlChaos)
        c = cc.chaos
        mode = self.regime[0] if self.regime else None
        if c >= self.chaos_enter or (mode == "chaos" and c >= self.chaos_hold):
            regime = ("chaos", None)
        elif (c <= self.control_enter or (mode == "control" and c <= self.control_hold)) and (team := self._dominant(st, cc)):
            regime = ("control", team)
        else:
            regime = None
        self.regime = regime
        if regime is None or regime == self.announced:
            return []
        win = st.window_bounds("5m")
        m = cc.components["match"]
        facts = [
            FactDraft(
                "match.chaos_5m",
                "Chaos index (0 calm, 1 chaotic)",
                round(c, 2),
                [metric_ref("match.chaos_5m", *win)],
                None,
                self.chaos_at_announce,
            ),
            FactDraft(
                "match.turnovers_per_min_5m",
                "Turnovers per team per minute",
                round(m["turnovers_per_min"], 1),
                [metric_ref("match.turnovers_per_min_5m", *win)],
            ),
            FactDraft(
                "match.mean_sequence_passes_5m",
                "Passes per possession",
                round(m["mean_sequence_passes"], 1),
                [metric_ref("match.mean_sequence_passes_5m", *win)],
            ),
            FactDraft(
                "match.transition_entropy_5m",
                "Possession transition entropy",
                round(m["transition_entropy"], 2),
                [metric_ref("match.transition_entropy_5m", *win)],
                "bits",
            ),
        ]
        teams: list[str] = []
        if regime[0] == "control":
            team = regime[1]
            teams = [team]
            facts[:0] = [
                FactDraft(
                    f"{team}.control_5m",
                    f"{_team_name(st, team)} control score",
                    round(cc.control[team], 2),
                    [metric_ref(f"{team}.control_5m", *win)],
                ),
                FactDraft(
                    f"{team}.possession_share_5m",
                    f"{_team_name(st, team)} share of passes (5 min)",
                    pct(st.window(team, "passes") / max(1.0, st.window(team, "passes") + st.window(st.opp(team), "passes"))),
                    [metric_ref(f"{team}.possession_share_5m", *win)],
                    "%",
                ),
            ]
            hint = f"{_team_name(st, team)} are in control: long possessions, few turnovers."
        else:
            hint = "The game has turned chaotic: turnovers up, possessions short, nobody settling."
        return [
            Draft(
                "control_vs_chaos", 3 if regime[0] == "chaos" else 2, 10000, facts, hint, f"cvc:{regime}:{ev.event_id}", "match", teams, []
            )
        ]

    def _dominant(self, st: MatchState, cc: ControlChaos) -> str | None:
        for t in st.team_ids:
            mine, theirs = cc.control.get(t), cc.control.get(st.opp(t))
            if mine is None or theirs is None:
                continue
            n, m = st.window(t, "passes"), st.window(st.opp(t), "passes")
            if mine >= self.min_control and mine - theirs >= self.min_control_margin and n / max(1.0, n + m) >= self.min_pass_share:
                return t
        return None

    def admitted(self, draft: Draft) -> None:
        """Remember the announced regime and its chaos index."""
        self.announced = self.regime
        self.chaos_at_announce = next(f.value for f in draft.facts if f.key == "match.chaos_5m")


class PlayerTagDetector(Detector):
    """Speed tags: sprints over 30 km/h and new match records for sprint, shot and pass speed."""

    kind = "player_tag"
    cooldown_s = 120.0
    min_record_kmh = {"sprint": 30.0, "shot_speed": 100.0, "pass_speed": 70.0}

    def __init__(self) -> None:
        self._seen = 0

    def detect(self, ev, updates, st):
        """A tag for each new notable speed."""
        rec = st.component(Records)
        new, self._seen = rec.marks[self._seen :], len(rec.marks)
        out = []
        for m in new:
            if m.value_kmh < self.min_record_kmh[m.kind]:
                continue
            ref = [event_ref(m.event_id)]
            name = _name(st, m.player_id)
            if m.kind == "sprint":
                facts = [FactDraft(f"{m.player_id}.sprint_top_speed_kmh", f"{name} top speed", m.value_kmh, ref, "km/h")]
                if ev.event_id == m.event_id:  # marks are recorded while applying their own event
                    facts.append(FactDraft(f"{m.player_id}.sprint_distance_m", "Sprint distance", ev.distance_m, ref, "m"))
                label, hint = "Fastest sprint of the match", f"{name} hits {m.value_kmh} km/h"
            else:
                what = "Shot speed" if m.kind == "shot_speed" else "Pass speed"
                facts = [FactDraft(f"{m.player_id}.{m.kind}_kmh", f"{name} {what.lower()}", m.value_kmh, ref, "km/h")]
                label, hint = f"Fastest {what.lower()} of the match", f"{name}: {what.lower()} {m.value_kmh} km/h"
            if m.is_record:
                prev_ref = [event_ref(m.previous_event_id)] if m.previous_event_id else []
                facts.append(FactDraft(f"match.max_{m.kind}_kmh", label, m.value_kmh, [*ref, *prev_ref], "km/h", m.previous_kmh))
                hint += ", a new match record."
            priority = 4 if m.kind == "sprint" and m.is_record else 3 if m.kind == "sprint" else 2
            out.append(
                Draft("player_tag", priority, 8000, facts, hint, f"tag:{m.kind}:{m.event_id}", m.player_id, [m.team_id], [m.player_id])
            )
        return out


class MilestoneDetector(Detector):
    """Braces, hat-tricks and career landmarks, one insight per player per event."""

    kind = "milestone"

    def __init__(self) -> None:
        self._seen = 0

    def detect(self, ev, updates, st):
        """A milestone insight for each player with new milestones."""
        rec = st.component(Records)
        new, self._seen = rec.milestones[self._seen :], len(rec.milestones)
        groups: dict[str, list] = {}
        for m in new:
            groups.setdefault(m.player_id, []).append(m)
        out = []
        for pid, ms in groups.items():
            name = _name(st, pid)
            goals = [event_ref(e) for e in st.goal_events[pid]]
            facts, parts = [], []
            for m in ms:
                if m.kind in ("brace", "hat_trick"):
                    facts.append(FactDraft(f"{pid}.match_goals", f"{name} goals this match", m.value, goals, None, m.previous_value))
                    parts.append("a brace" if m.kind == "brace" else "a hat-trick")
                elif m.kind == "career_goal":
                    roster = metric_ref(f"{pid}.career_goals_before_match", None, None)
                    facts.append(
                        FactDraft(f"{pid}.career_goals", f"{name} career goals", m.value, [*goals, roster], None, m.previous_value)
                    )
                    parts.append(f"career goal number {m.value}")
                else:
                    roster = metric_ref(f"{pid}.career_appearances_before_match", None, None)
                    facts.append(
                        FactDraft(
                            f"{pid}.career_appearances",
                            f"{name} career appearances",
                            m.value,
                            [event_ref(m.event_id), roster],
                            None,
                            m.previous_value,
                        )
                    )
                    parts.append(f"appearance number {m.value}")
            priority = 4 if any(m.kind != "career_appearance" for m in ms) else 2
            hint = f"Milestone for {name}: " + " and ".join(parts) + "."
            key = "milestone:" + ",".join(f"{m.kind}:{pid}:{m.value}" for m in ms)
            out.append(Draft("milestone", priority, 10000, facts, hint, key, pid, [ms[0].team_id], [pid]))
        return out


class PeriodSummaryDetector(Detector):
    """Half-time and full-time numbers: score, share of passes, shots, xG, completion, fastest sprint."""

    kind = "period_summary"

    def detect(self, ev, updates, st):
        """A summary at the end of each period."""
        if ev.type != "period_end":
            return []
        end = event_ref(ev.event_id)
        win = (0.0, st.now)
        all_goals = sorted(e for ids in st.goal_events.values() for e in ids)
        facts = [
            FactDraft(
                "match.score", f"Score ({st.home_id}-{st.away_id})", f"{ev.home_score}-{ev.away_score}", [end, *map(event_ref, all_goals)]
            )
        ]
        total_passes = sum(st.totals[t]["passes"] for t in st.team_ids) or 1.0
        for t in st.team_ids:
            tot, name = st.totals[t], _team_name(st, t)
            facts += [
                FactDraft(
                    f"{t}.possession_share",
                    f"{name} share of passes",
                    pct(tot["passes"] / total_passes),
                    [metric_ref(f"{t}.passes", *win)],
                    "%",
                ),
                FactDraft(f"{t}.shots", f"{name} shots", int(tot["shots"]), [metric_ref(f"{t}.shots", *win)]),
                FactDraft(f"{t}.xg_total", f"{name} xG", round(tot["xg"], 2), [metric_ref(f"{t}.xg_total", *win)], "xG"),
                FactDraft(
                    f"{t}.pass_completion",
                    f"{name} pass completion",
                    pct(tot["passes_complete"] / tot["passes"]) if tot["passes"] else 0,
                    [metric_ref(f"{t}.pass_completion", *win)],
                    "%",
                ),
            ]
        rec = st.component(Records)
        best = rec.best.get("sprint") if rec else None
        players = []
        if best is not None:
            players.append(best.player_id)
            facts.append(
                FactDraft(
                    "match.max_sprint_kmh",
                    f"Fastest sprint ({_name(st, best.player_id)})",
                    best.value_kmh,
                    [event_ref(best.event_id)],
                    "km/h",
                )
            )
        label = "Half-time" if ev.period == 1 else "Full-time"
        hint = f"{label}: {st.meta.home.name} {ev.home_score}-{ev.away_score} {st.meta.away.name}."
        return [Draft("period_summary", 3, 15000, facts, hint, f"period:{ev.period}", "match", list(st.team_ids), players)]


def default_detectors() -> list[Detector]:
    """The nine detectors, in the order they run."""
    return [
        GoalDetector(),
        KeyPassDetector(),
        ShotQualityDetector(),
        MilestoneDetector(),
        PlayerTagDetector(),
        PressChangeDetector(),
        MomentumShiftDetector(),
        ControlChaosDetector(),
        PeriodSummaryDetector(),
    ]
