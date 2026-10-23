"""Frozen per-insight view of match state, and the Analyst's tools over it.

The warm path runs after the hot path has moved on, so each insight carries a
snapshot taken when it fired. Tools never compute anything new: they read the
snapshot. Every number a tool returns is registered as a *candidate fact* with
evidence. If the Analyst selects it, it joins the insight's facts and the
Narrator may cite it. Numbers that never became facts cannot reach the screen.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Annotated

from pydantic import Field

from ..contracts.insight import EvidenceRef, Fact, Insight
from ..state import WINDOWS_S, ControlChaos, MatchState, Momentum

# metric -> (numerator counter on the team, denominator spec, unit, label)
# denominator: None = raw count/sum, "own" = team passes, "opp" = opponent passes, "both" = both teams' passes
WINDOW_METRICS: dict[str, tuple[str, str | None, str | None, str]] = {
    "passes": ("passes", None, None, "passes"),
    "pass_completion": ("passes_complete", "own", "%", "pass completion"),
    "long_ball_share": ("long_passes", "own", "%", "long-ball share"),
    "possession_share": ("passes", "both", "%", "share of passes"),
    "pressures_per_opp_pass": ("pressures", "opp", None, "pressures per opponent pass"),
    "turnovers_lost": ("turnovers_lost", None, None, "turnovers lost"),
    "shots": ("shots", None, None, "shots"),
    "xg": ("xg", None, "xG", "xG"),
    "final_third_passes": ("passes_final_third", None, None, "completed passes into the final third"),
}
PLAYER_STATS = ("goals", "passes", "passes_complete", "shots", "xg", "pressures", "tackles_won", "interceptions", "top_speed_kmh")


@dataclass
class InsightContext:
    insight: Insight
    elapsed_s: float
    team_names: dict[str, str]
    player_info: dict[str, dict]
    state: dict
    windows: dict[str, dict]  # "NVL.pass_completion.5m" -> {"value", "start", "end"}
    players: dict[str, dict[str, float]]


def capture(st: MatchState, insight: Insight) -> InsightContext:
    """Snapshot what the Analyst may look at, at the moment the insight fired. O(metrics), only on insights."""
    windows: dict[str, dict] = {}
    for label in WINDOWS_S:
        lo, hi = st.window_bounds(label)
        for t in st.team_ids:
            o = st.opp(t)
            for metric, (num, den, unit, _) in WINDOW_METRICS.items():
                n = st.window(t, num, label)
                d = {
                    None: None,
                    "own": st.window(t, "passes", label),
                    "opp": st.window(o, "passes", label),
                    "both": st.window(t, "passes", label) + st.window(o, "passes", label),
                }[den]
                if d == 0:
                    continue
                v = n if d is None else n / d
                if unit == "%":
                    v = int(round(100 * v))
                elif isinstance(v, float):
                    v = round(v, 2)
                windows[f"{t}.{metric}.{label}"] = {"value": v, "start": lo, "end": hi}
    mom, cc = st.component(Momentum), st.component(ControlChaos)
    state = {
        "score": dict(st.score),
        "xg": {t: round(st.totals[t]["xg"], 2) for t in st.team_ids},
        "momentum_share": {t: int(round(100 * mom.share(t, st))) for t in st.team_ids} if mom else {},
        "chaos_5m": round(cc.chaos, 2) if cc and cc.chaos is not None else None,
        "control_5m": {t: round(v, 2) for t, v in cc.control.items() if v is not None} if cc else {},
    }
    players = {pid: {k: (round(v, 2) if isinstance(v, float) else v) for k, v in pt.items()} for pid, pt in st.player_totals.items()}
    info = {
        pid: {
            "name": p.name,
            "short_name": p.short_name,
            "team_id": st.team_of[pid],
            "position": p.position,
            "role": p.role,
            "career_goals_before": p.career_goals,
            "career_appearances_before": p.career_appearances,
        }
        for pid, p in st.players.items()
    }
    names = {st.meta.home.team_id: st.meta.home.name, st.meta.away.team_id: st.meta.away.name}
    return InsightContext(insight, st.now, names, info, state, windows, players)


@dataclass
class ToolBox:
    """Analyst tools bound to one InsightContext. Registers every returned number as a candidate fact."""

    ctx: InsightContext
    candidates: dict[str, Fact] = field(default_factory=dict)  # fact_id -> Fact
    calls: list[dict] = field(default_factory=list)

    def _candidate(self, key: str, label: str, value, unit: str | None, evidence: list[EvidenceRef]) -> dict:
        for f in self.candidates.values():
            if f.key == key:
                return {"fact_id": f.fact_id, "label": f.label, "value": f.value, "unit": f.unit}
        fid = f"{self.ctx.insight.insight_id}-C{len(self.candidates) + 1}"
        self.candidates[fid] = Fact(fact_id=fid, key=key, label=label, value=value, unit=unit, evidence=evidence)
        return {"fact_id": fid, "label": label, "value": value, "unit": unit}

    def _log(self, name: str, args: dict, result) -> str:
        self.calls.append({"tool": name, "args": args})
        return json.dumps(result, ensure_ascii=False)

    # The four tools. Docstrings and Field descriptions are what the model sees.
    def get_facts(self) -> str:
        """Return the facts the detector attached to this moment, with fact ids."""
        facts = [
            {"fact_id": f.fact_id, "label": f.label, "value": f.value, "unit": f.unit, "previous_value": f.previous_value}
            for f in self.ctx.insight.facts
        ]
        return self._log("get_facts", {}, facts)

    def get_state(self) -> str:
        """Return match state when the moment happened: score, xG, momentum share, chaos and control scores."""
        s, end = self.ctx.state, self.ctx.elapsed_s
        out = []
        for t, name in self.ctx.team_names.items():
            out.append(
                self._candidate(
                    f"{t}.goals",
                    f"{name} goals",
                    s["score"][t],
                    None,
                    [EvidenceRef(kind="metric", ref=f"{t}.goals", window_start_s=0.0, window_end_s=end)],
                )
            )
            out.append(
                self._candidate(
                    f"{t}.xg_total",
                    f"{name} xG",
                    s["xg"][t],
                    "xG",
                    [EvidenceRef(kind="metric", ref=f"{t}.xg_total", window_start_s=0.0, window_end_s=end)],
                )
            )
            if t in s["momentum_share"]:
                ref = EvidenceRef(kind="metric", ref=f"{t}.momentum", window_start_s=max(0.0, end - 480.0), window_end_s=end)
                out.append(self._candidate(f"{t}.momentum_share", f"{name} share of momentum", s["momentum_share"][t], "%", [ref]))
            if t in s["control_5m"]:
                ref = EvidenceRef(kind="metric", ref=f"{t}.control_5m", window_start_s=max(0.0, end - 300.0), window_end_s=end)
                out.append(self._candidate(f"{t}.control_5m", f"{name} control score (5 min)", s["control_5m"][t], None, [ref]))
        if s["chaos_5m"] is not None:
            ref = EvidenceRef(kind="metric", ref="match.chaos_5m", window_start_s=max(0.0, end - 300.0), window_end_s=end)
            out.append(self._candidate("match.chaos_5m", "Chaos index (5 min)", s["chaos_5m"], None, [ref]))
        return self._log("get_state", {}, out)

    def get_player(self, player_id: Annotated[str, Field(description="Player id, e.g. NVL-09")]) -> str:
        """Return a player's profile and match stats so far: goals, passes, completion, shots, xG, top speed, career totals."""
        info = self.ctx.player_info.get(player_id)
        if info is None:
            return self._log("get_player", {"player_id": player_id}, {"error": f"unknown player {player_id}"})
        stats = self.ctx.players.get(player_id, {})
        name, end = info["short_name"], self.ctx.elapsed_s
        out = {"player_id": player_id, "name": info["name"], "team_id": info["team_id"], "role": info["role"], "stats": []}

        def ref(stat: str) -> list[EvidenceRef]:
            return [EvidenceRef(kind="metric", ref=f"{player_id}.{stat}", window_start_s=0.0, window_end_s=end)]

        labels = {
            "goals": "goals this match",
            "passes": "passes",
            "shots": "shots",
            "xg": "xG",
            "pressures": "pressures",
            "tackles_won": "tackles won",
            "interceptions": "interceptions",
            "top_speed_kmh": "top speed",
        }
        for stat in PLAYER_STATS:
            if stat == "passes_complete" or not stats.get(stat):
                continue
            unit = "xG" if stat == "xg" else "km/h" if stat == "top_speed_kmh" else None
            out["stats"].append(self._candidate(f"{player_id}.{stat}", f"{name} {labels[stat]}", stats[stat], unit, ref(stat)))
        if stats.get("passes"):
            pc = int(round(100 * stats.get("passes_complete", 0) / stats["passes"]))
            out["stats"].append(self._candidate(f"{player_id}.pass_completion", f"{name} pass completion", pc, "%", ref("pass_completion")))
        for stat, label in (
            ("career_goals_before", "career goals before today"),
            ("career_appearances_before", "career appearances before today"),
        ):
            roster = [EvidenceRef(kind="metric", ref=f"{player_id}.{stat.replace('_before', '_before_match')}")]
            out["stats"].append(self._candidate(f"{player_id}.{stat}", f"{name} {label}", info[stat], None, roster))
        return self._log("get_player", {"player_id": player_id}, out)

    def get_window_stats(
        self,
        team_id: Annotated[str, Field(description="Team id, e.g. NVL or SLM")],
        metric: Annotated[str, Field(description=f"One of: {', '.join(WINDOW_METRICS)}")],
        window: Annotated[str, Field(description="Rolling window: 5m or 10m")] = "5m",
    ) -> str:
        """Return one team metric over the last 5 or 10 minutes before the moment."""
        args = {"team_id": team_id, "metric": metric, "window": window}
        w = self.ctx.windows.get(f"{team_id}.{metric}.{window}")
        if w is None or metric not in WINDOW_METRICS or team_id not in self.ctx.team_names:
            return self._log("get_window_stats", args, {"error": "no data for that team, metric and window"})
        _, _, unit, label = WINDOW_METRICS[metric]
        key = f"{team_id}.{metric}_{window}"
        ev = [EvidenceRef(kind="metric", ref=key, window_start_s=round(w["start"], 2), window_end_s=w["end"])]
        mins = int(WINDOWS_S[window] // 60)
        return self._log(
            "get_window_stats", args, self._candidate(key, f"{self.ctx.team_names[team_id]} {label} ({mins} min)", w["value"], unit, ev)
        )

    def tools(self) -> list:
        return [self.get_facts, self.get_state, self.get_player, self.get_window_stats]
