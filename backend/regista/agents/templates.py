"""Deterministic template Narrator: the fallback that always passes verification.

Every claim is a phrase whose numbers and names come from facts, and it cites
exactly those facts. Viewing mode decides which claims appear:

* analyst: up to four evidence-heavy claims and a technical stat callout
* casual: one story line, a fan-colour line for a favorite club, the telling stat
* player_focus: lines about the focus player when involved, otherwise the casual line
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..contracts.events import MatchMeta
from ..contracts.insight import Claim, Fact, FanProfile, Insight, RenderedInsight, StatCallout, Verification
from .phrases import PHRASES, STAT_LABELS, VALUES
from .verifier import BODY_MAX, HEADLINE_MAX


@dataclass
class Line:
    msg: str
    slots: dict[str, str] = field(default_factory=dict)  # placeholder -> normalized fact key (suffix ":prev" for previous_value)
    extra: dict[str, str] = field(default_factory=dict)  # placeholder -> literal (team names)
    cite: tuple[str, ...] = ()  # facts cited without a placeholder


class FactView:
    """Facts addressable by normalized keys: team./opp. (relative to the insight's team), home./away., player."""

    def __init__(self, insight: Insight, meta: MatchMeta) -> None:
        self.insight = insight
        home, away = meta.home.team_id, meta.away.team_id
        team = insight.entities.team_ids[0] if insight.entities.team_ids else None
        players = {p.player_id for t in (meta.home, meta.away) for p in t.players}
        self.map: dict[str, Fact] = {}
        for f in insight.facts:
            prefix, _, rest = f.key.partition(".")
            keys = [f.key]
            if prefix in (home, away):
                keys.append(("home." if prefix == home else "away.") + rest)
                if team:
                    keys.append(("team." if prefix == team else "opp.") + rest)
            elif prefix in players:
                keys.append("player." + rest)
            for k in keys:
                self.map.setdefault(k, f)

    def get(self, key: str) -> Fact | None:
        return self.map.get(key)


def fmt_number(v: float | int, lang: str) -> str:
    s = str(v) if isinstance(v, int) else f"{v:.2f}".rstrip("0").rstrip(".")
    return s.replace(".", ",") if lang == "es" else s


def fmt_value(v, lang: str) -> str:
    if isinstance(v, str):
        return VALUES[lang].get(v, v)
    return fmt_number(v, lang)


class TemplateNarrator:
    def __init__(self, meta: MatchMeta) -> None:
        self.meta = meta
        self.team_name = {t.team_id: t.name for t in (meta.home, meta.away)}
        self.short = {t.team_id: t.short_name for t in (meta.home, meta.away)}

    # ------------------------------------------------------------------ #
    def _fill(self, line: Line, view: FactView, lang: str) -> tuple[str, list[str]] | None:
        values: dict[str, str] = dict(line.extra)
        cited: list[str] = []
        for ph, key in line.slots.items():
            k, _, part = key.partition(":")
            f = view.get(k)
            if f is None:
                return None
            v = f.previous_value if part == "prev" else f.value
            if v is None:
                return None
            values[ph] = fmt_value(v, lang)
            if f.fact_id not in cited:
                cited.append(f.fact_id)
        for k in line.cite:
            f = view.get(k)
            if f is not None and f.fact_id not in cited:
                cited.append(f.fact_id)
        return PHRASES[lang][line.msg].format(**values), cited

    def render(self, insight: Insight, profile: FanProfile) -> RenderedInsight:
        view = FactView(insight, self.meta)
        lang = profile.language if profile.language in PHRASES else "en"
        headline, lines, stat_keys = self._spec(insight, view, profile)
        head = self._fill(headline, view, lang)
        head_text = head[0] if head else insight.kind.replace("_", " ").title()
        claims: list[Claim] = []
        for line in lines:
            filled = self._fill(line, view, lang)
            if filled is not None:
                claims.append(Claim(text=filled[0], fact_ids=filled[1]))
        while len(claims) > 1 and len(" ".join(c.text for c in claims)) > BODY_MAX:
            claims.pop()
        stat = None
        for key in stat_keys:
            f = view.get(key)
            if f is not None:
                label = STAT_LABELS[lang].get(key, f.label)
                unit = "" if f.unit is None else ("%" if f.unit == "%" else f" {f.unit}")
                stat = StatCallout(label=label[:40], value=f"{fmt_value(f.value, lang)}{unit}", fact_id=f.fact_id)
                break
        return RenderedInsight(
            insight_id=insight.insight_id,
            profile_id=profile.profile_id,
            language=lang,
            mode=profile.mode,
            headline=head_text[:HEADLINE_MAX],
            body=" ".join(c.text for c in claims),
            stat_callout=stat,
            claims=claims,
            verification=Verification(status="pending"),
        )

    # ------------------------------------------------------------------ #
    def _names(self, insight: Insight) -> dict[str, str]:
        home, away = self.meta.home.team_id, self.meta.away.team_id
        names = {"home": self.short[home], "away": self.short[away]}
        if insight.entities.team_ids:
            t = insight.entities.team_ids[0]
            o = away if t == home else home
            names.update(team=self.team_name[t], opp=self.team_name[o])
        return names

    def _colour(self, insight: Insight, profile: FanProfile, kind: str) -> list[Line]:
        fav = profile.favorite_team_id
        if not fav or profile.mode == "analyst" or not insight.entities.team_ids:
            return []
        msg = f"{kind}.fav_for" if fav == insight.entities.team_ids[0] else f"{kind}.fav_against"
        return [Line(msg, extra={"fav": self.team_name[fav]})]

    def _spec(self, ins: Insight, view: FactView, profile: FanProfile) -> tuple[Line, list[Line], list[str]]:
        n = self._names(ins)
        mode = profile.mode
        focus = profile.focus_player_id
        kind = ins.kind

        if kind == "goal":
            head = Line("goal.h", {"scorer": "goal.scorer", "score": "match.score"}, n)
            assist = (
                Line("goal.assist_typed", {"assister": "goal.assist", "assist_type": "assist.type"})
                if view.get("assist.type")
                else Line("goal.assist", {"assister": "goal.assist"})
            )
            analyst = [
                Line(
                    "goal.finish", {"scorer": "goal.scorer", "body_part": "shot.body_part", "distance": "shot.distance_m", "xg": "shot.xg"}
                ),
                Line(
                    "goal.chain",
                    {
                        "won_by": "goal.won_ball_by",
                        "turnover_dist": "goal.turnover_distance_to_goal_m",
                        "secs": "goal.seconds_from_turnover",
                    },
                ),
                Line("goal.press", {"share": "team.pressed_pass_share_5m", "share_prev": "team.pressed_pass_share_5m:prev"}, n),
                assist,
            ]
            f = view.get("player.match_goals")
            if f is not None and isinstance(f.value, int) and f.value >= 2:
                analyst.insert(1, Line("goal.brace", {"n": "player.match_goals", "scorer": "goal.scorer"}))
            casual = [Line("goal.casual", {"scorer": "goal.scorer", "score": "match.score"}, n), *self._colour(ins, profile, "goal")]
            focus_lines: list[Line] = []
            if focus and focus in ins.entities.player_ids:
                if focus == ins.entities.player_ids[0]:
                    focus_lines.append(Line("goal.focus_scorer", {"scorer": "goal.scorer", "n": "player.match_goals"}))
                elif (a := view.get("goal.assist")) is not None and self._pid(a.value) == focus:
                    focus_lines.append(Line("goal.focus_assist", {"assister": "goal.assist", "assist_type": "assist.type"}))
                else:
                    focus_lines.append(Line("goal.focus_won", {"won_by": "goal.won_ball_by"}))
                focus_lines.append(casual[0])
            return head, self._pick(mode, analyst, casual, focus_lines), (["shot.xg"] if mode == "analyst" else ["shot.distance_m"])

        if kind == "shot_quality":
            head = Line("shot_quality.h", {"player": "shot.player"})
            analyst = [
                Line(
                    "shot_quality.a1", {"player": "shot.player", "xg": "shot.xg", "distance": "shot.distance_m", "outcome": "shot.outcome"}
                ),
                Line("shot_quality.a2", {"xg_total": "team.xg_total"}, n),
            ]
            casual = [Line("shot_quality.casual", {"player": "shot.player", "outcome": "shot.outcome"})]
            return head, self._pick(mode, analyst, casual, casual if self._involved(ins, focus) else []), ["shot.xg"]

        if kind == "key_pass":
            head = Line("key_pass.h", {"passer": "pass.player"})
            analyst = [
                Line(
                    "key_pass.a1",
                    {"passer": "pass.player", "pass_type": "pass.type", "length": "pass.length_m", "difficulty": "pass.difficulty"},
                ),
                Line("key_pass.a2", {"receiver": "pass.receiver", "xg": "shot.xg", "outcome": "shot.outcome"}),
            ]
            casual = [Line("key_pass.casual", {"pass_type": "pass.type", "passer": "pass.player", "receiver": "pass.receiver"})]
            return head, self._pick(mode, analyst, casual, analyst[:1] + casual if self._involved(ins, focus) else []), ["pass.difficulty"]

        if kind == "momentum_shift":
            head = Line("momentum_shift.h", extra=n)
            share = view.get("team.momentum_share")
            a1 = (
                Line("momentum_shift.a1_prev", {"share": "team.momentum_share", "share_prev": "team.momentum_share:prev"}, n)
                if share is not None and share.previous_value is not None
                else Line("momentum_shift.a1", {"share": "team.momentum_share"}, n)
            )
            analyst = [a1, Line("momentum_shift.a2", {"n": "team.final_third_passes_5m"})]
            xg = view.get("team.xg_10m")
            if xg is not None and xg.value:
                analyst.append(Line("momentum_shift.a3", {"xg": "team.xg_10m"}))
            casual = [Line("momentum_shift.casual", extra=n, cite=("team.momentum_share",))]
            return head, self._pick(mode, analyst, casual, []), ["team.momentum_share"]

        if kind == "press_change":
            head = Line("press_change.h", extra=n)
            analyst = [
                Line("press_change.a1", {"share": "team.pressed_pass_share_5m", "share_prev": "team.pressed_pass_share_5m:prev"}, n),
                Line("press_change.a2", {"ppp": "team.pressures_per_opp_pass_5m", "ppp_prev": "team.pressures_per_opp_pass_5m:prev"}, n),
                Line("press_change.a3", {"comp": "opp.pass_completion_5m"}, n),
                Line("press_change.a4", {"start": "team.press_change_start"}),
            ]
            casual = [
                Line("press_change.casual", extra=n, cite=("team.pressed_pass_share_5m",)),
                *self._colour(ins, profile, "press_change"),
            ]
            return head, self._pick(mode, analyst, casual, []), ["team.pressed_pass_share_5m"]

        if kind == "control_vs_chaos":
            if ins.entities.team_ids:
                head = Line("control.h", extra=n)
                analyst = [
                    Line("control.a1", {"ctl": "team.control_5m", "share": "team.possession_share_5m"}, n),
                    Line("control.a2", {"seq": "match.mean_sequence_passes_5m", "to": "match.turnovers_per_min_5m"}),
                ]
                casual = [Line("control.casual", extra=n, cite=("team.control_5m",))]
                return head, self._pick(mode, analyst, casual, []), ["team.control_5m"]
            head = Line("chaos.h")
            chaos = view.get("match.chaos_5m")
            a1 = (
                Line("chaos.a1_prev", {"chaos": "match.chaos_5m", "chaos_prev": "match.chaos_5m:prev"})
                if chaos is not None and chaos.previous_value is not None
                else Line("chaos.a1", {"chaos": "match.chaos_5m"})
            )
            analyst = [
                a1,
                Line("chaos.a2", {"to": "match.turnovers_per_min_5m", "seq": "match.mean_sequence_passes_5m"}),
                Line("chaos.a3", {"ent": "match.transition_entropy_5m"}),
            ]
            casual = [Line("chaos.casual", cite=("match.chaos_5m",))]
            return head, self._pick(mode, analyst, casual, []), ["match.chaos_5m"]

        if kind == "player_tag":
            for tag, speed_key in (
                ("sprint", "player.sprint_top_speed_kmh"),
                ("shot_speed", "player.shot_speed_kmh"),
                ("pass_speed", "player.pass_speed_kmh"),
            ):
                if view.get(speed_key) is None:
                    continue
                pname = {"player": self._player_name(ins.entities.player_ids[0])}
                head = Line(f"{tag}.h", {"speed": speed_key}, pname)
                if tag == "sprint" and view.get("player.sprint_distance_m"):
                    a1 = Line("sprint.a1", {"speed": speed_key, "dist": "player.sprint_distance_m"}, pname)
                else:
                    a1 = Line(f"{tag}.a1" if tag != "sprint" else "sprint.a1_nodist", {"speed": speed_key}, pname)
                record_key = f"match.max_{tag}_kmh"
                analyst = [a1]
                if view.get(record_key) is not None:
                    analyst.append(Line(f"{tag}.record", {"prev": f"{record_key}:prev"}))
                return head, self._pick(mode, analyst, analyst, analyst), [speed_key]

        if kind == "milestone":
            pname = {"player": self._player_name(ins.entities.player_ids[0])}
            head = Line("milestone.h", extra=pname)
            lines = []
            mg = view.get("player.match_goals")
            if mg is not None:
                lines.append(Line("milestone.hat_trick" if mg.value == 3 else "milestone.brace", {"n": "player.match_goals"}, pname))
            if view.get("player.career_goals") is not None:
                lines.append(Line("milestone.career_goal", {"n": "player.career_goals"}, pname))
            if view.get("player.career_appearances") is not None:
                lines.append(Line("milestone.career_appearance", {"n": "player.career_appearances"}, pname))
            stat = ["player.match_goals", "player.career_goals", "player.career_appearances"]
            return head, lines, stat

        if kind in ("period_summary", "recap"):
            return self._summary_spec(ins, view, profile, n)

        return Line("chaos.h"), [], []

    def _summary_spec(self, ins: Insight, view: FactView, profile: FanProfile, n: dict[str, str]) -> tuple[Line, list[Line], list[str]]:
        second = ins.clock.period == 2
        xg = Line(
            "recap.xg" if ins.kind == "recap" else "period_summary.casual",
            {"hx": "home.xg_total", "ax": "away.xg_total", "hs": "home.shots", "as_": "away.shots"},
            n,
        )
        if ins.kind == "period_summary":
            head = Line("period_summary.h2" if second else "period_summary.h1", {"score": "match.score"}, n)
            analyst = [
                Line("period_summary.a1", {"hp": "home.possession_share", "ap": "away.possession_share"}, n),
                Line("period_summary.a2", {"hs": "home.shots", "as_": "away.shots", "hx": "home.xg_total", "ax": "away.xg_total"}),
                Line("period_summary.a3", {"hc": "home.pass_completion", "ac": "away.pass_completion"}, n),
                Line("period_summary.a4", {"sprint": "match.max_sprint_kmh"}),
            ]
            return head, self._pick(profile.mode, analyst, [xg], [xg]), ["match.score"]
        head = Line("recap.h2" if second else "recap.h1", {"score": "match.score"}, n)
        lines = [Line("recap.goal", {"goal": f.key}) for f in ins.facts if f.key.startswith("recap.goal")]
        for f in ins.facts:
            if f.key.endswith(".recap_press_start"):
                lines.append(Line("recap.press", {"start": f.key}, {"team": self.team_name[f.key.split(".")[0]]}))
            elif f.key == "recap.chaos_start":
                lines.append(Line("recap.chaos", {"start": f.key}))
            elif f.key.endswith(".career_goals"):
                lines.append(Line("milestone.career_goal", {"n": f.key}, {"player": self._player_name(f.key.split(".")[0])}))
        lines.append(Line("recap.xg", {"hx": "home.xg_total", "ax": "away.xg_total"}))
        return head, lines, ["match.score"]

    # ------------------------------------------------------------------ #
    @staticmethod
    def _pick(mode: str, analyst: list[Line], casual: list[Line], focus: list[Line]) -> list[Line]:
        if mode == "analyst":
            return analyst
        if mode == "player_focus" and focus:
            return focus
        return casual

    @staticmethod
    def _involved(ins: Insight, focus: str | None) -> bool:
        return focus is not None and focus in ins.entities.player_ids

    def _player_name(self, pid: str) -> str:
        for t in (self.meta.home, self.meta.away):
            for p in t.players:
                if p.player_id == pid:
                    return p.short_name
        return pid

    def _pid(self, short_name) -> str | None:
        for t in (self.meta.home, self.meta.away):
            for p in t.players:
                if p.short_name == short_name:
                    return p.player_id
        return None
