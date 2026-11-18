"""Calls the hot path makes about the next few minutes, graded from the event stream when they fall due.

A momentum shift or a press change triggers a call with a fixed horizon:

- ``momentum_xg``: the team with momentum creates more xG than the opponent over the next 10 minutes.
- ``press_completion``: the pressed team's pass completion stays below its pre-call level for 10 minutes.

Each call states the chance it comes true: its hit rate on the training seeds (``state/models/predictions.json``,
written by ``scripts/fit_predictions.py``). When the horizon ends, or the half ends after at least 5 minutes,
the call is graded right or wrong from the state's own match totals, and the running record goes with the result.
A call cut short by the half before 5 minutes is void and never graded. Never reads ground truth.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..contracts.events import format_clock
from ..state import MatchState
from ..state.logistic import MODELS_DIR
from .base import Draft, FactDraft, metric_ref

HORIZON_S = 600.0
MIN_SPAN_S = 300.0
CALL_KINDS = ("momentum_xg", "press_completion")


def load_base_rates(path: Path = MODELS_DIR / "predictions.json") -> dict[str, dict]:
    """Fitted hit rates per call kind: {kind: {"p": 0-1, "n": calls, "hits": calls right}}; empty if not fitted."""
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


@dataclass
class Call:
    """One open call: what it is about, when it was made and the totals it will be graded against."""

    kind: str
    team: str
    opp: str
    made_s: float
    made_clock: str
    period: int
    probability: int | None
    start: dict[str, float]  # match totals at the call, keyed "TEAM.counter"
    baseline: float | None = None  # press_completion: the pressed team's completion before the call


def _pct(x: float) -> int:
    return round(100 * x)


class Predictor:
    """Makes calls on momentum shifts and press changes, and grades them when they fall due."""

    def __init__(self, base_rates: dict[str, dict] | None = None) -> None:
        self.base_rates = load_base_rates() if base_rates is None else base_rates
        self.open: list[Call] = []
        self.graded: list[tuple[Call, bool]] = []

    def step(self, ev, new_kinds: list[tuple[str, list[str]]], st: MatchState) -> list[Draft]:
        """Drafts for this event: results of calls that fell due, then calls triggered by the insights just admitted."""
        out = []
        period_over = ev.type == "period_end"
        for call in list(self.open):
            span = st.now - call.made_s
            if span >= HORIZON_S or period_over:
                self.open.remove(call)
                if span >= MIN_SPAN_S:
                    out.append(self._grade(call, span, st))
        for kind, team_ids in new_kinds:
            if not team_ids or period_over:
                continue
            if kind == "momentum_shift":
                out += self._call("momentum_xg", team_ids[0], st)
            elif kind == "press_change":
                out += self._call("press_completion", st.opp(team_ids[0]), st)
        return out

    def _totals(self, st: MatchState) -> dict[str, float]:
        return {f"{t}.{k}": st.totals[t][k] for t in st.team_ids for k in ("xg", "passes", "passes_complete")}

    def _call(self, kind: str, team: str, st: MatchState) -> list[Draft]:
        if any(c.kind == kind and c.team == team for c in self.open):
            return []
        rate = self.base_rates.get(kind)
        prob = _pct(rate["p"]) if rate else None
        tot = st.totals[team]
        baseline = tot["passes_complete"] / tot["passes"] if tot["passes"] else None
        if kind == "press_completion" and baseline is None:
            return []
        clock = format_clock(st.period, st.now - st.period_start_s)
        call = Call(kind, team, st.opp(team), st.now, clock, st.period, prob, self._totals(st), baseline)
        self.open.append(call)
        name, opp = _team(st, team), _team(st, call.opp)
        window = [metric_ref(f"prediction.{kind}", st.now, st.now + HORIZON_S)]
        facts = []
        if prob is not None:
            facts.append(FactDraft("prediction.probability", "Chance this call comes true", prob, window, "%"))
        facts.append(FactDraft("prediction.horizon_min", f"Minutes the call on {name} covers", int(HORIZON_S // 60), window, "min"))
        if kind == "momentum_xg":
            claim = f"{name} will create more xG than {opp} over the next 10 minutes"
            facts.append(
                FactDraft(
                    f"{team}.xg_total", f"{name} xG so far", round(tot["xg"], 2), [metric_ref(f"{team}.xg_total", None, st.now)], "xG"
                )
            )
        else:
            claim = f"{name}'s pass completion will stay below {_pct(baseline)}% for the next 10 minutes"
            facts.append(
                FactDraft(
                    f"{team}.pass_completion_before_call",
                    f"{name} pass completion before the call",
                    _pct(baseline),
                    [metric_ref(f"{team}.pass_completion", None, st.now)],
                    "%",
                )
            )
        if rate:
            facts.append(FactDraft("prediction.sample", "Past calls of this kind", int(rate["n"]), window))
        chance = f" Calls like this came true {prob}% of the time in past matches." if prob is not None else ""
        hint = f"Regista's call: {claim}.{chance}"
        teams = [team, call.opp] if kind == "momentum_xg" else [team]
        return [Draft("prediction", 2, 8000, facts, hint, f"call:{kind}:{team}:{st.now:.1f}", team, teams, [])]

    def _grade(self, call: Call, span: float, st: MatchState) -> Draft:
        now = self._totals(st)

        def delta(team: str, counter: str) -> float:
            key = f"{team}.{counter}"
            return now[key] - call.start[key]

        lo, hi = call.made_s, st.now
        name, opp = _team(st, call.team), _team(st, call.opp)
        facts: list[FactDraft] = []
        if call.kind == "momentum_xg":
            mine, theirs = round(delta(call.team, "xg"), 2), round(delta(call.opp, "xg"), 2)
            right = mine > theirs
            facts += [
                FactDraft(f"{call.team}.xg_since_call", f"{name} xG since the call", mine, [metric_ref(f"{call.team}.xg", lo, hi)], "xG"),
                FactDraft(f"{call.opp}.xg_since_call", f"{opp} xG since the call", theirs, [metric_ref(f"{call.opp}.xg", lo, hi)], "xG"),
            ]
            outcome = f"{name} {mine} xG to {opp}'s {theirs}"
        else:
            passes = delta(call.team, "passes")
            comp = delta(call.team, "passes_complete") / passes if passes else call.baseline
            right = comp < call.baseline
            facts.append(
                FactDraft(
                    f"{call.team}.pass_completion_since_call",
                    f"{name} pass completion since the call",
                    _pct(comp),
                    [metric_ref(f"{call.team}.pass_completion", lo, hi)],
                    "%",
                    _pct(call.baseline),
                )
            )
            outcome = f"{name} completed {_pct(comp)}% of passes, against {_pct(call.baseline)}% before the call"
        self.graded.append((call, right))
        n_right = sum(r for _, r in self.graded)
        record = [metric_ref("prediction.record", None, hi)]
        facts = [
            FactDraft(
                "prediction.result",
                f"Result of the call on {name}",
                "right" if right else "wrong",
                [metric_ref(f"prediction.{call.kind}", lo, hi)],
            ),
            *facts,
            FactDraft(
                "prediction.minutes",
                f"Minutes since the call on {name}",
                int(span // 60),
                [metric_ref(f"prediction.{call.kind}", lo, hi)],
                "min",
            ),
            FactDraft("prediction.call_made", f"Call on {name} made at", call.made_clock, [metric_ref(f"prediction.{call.kind}", lo, lo)]),
            FactDraft("prediction.calls_right", "Calls right so far", n_right, record),
            FactDraft("prediction.calls_graded", "Calls graded so far", len(self.graded), record),
        ]
        verdict = "came true" if right else "did not come true"
        hint = f"The {call.made_clock} call {verdict}: {outcome}. Record: {n_right} of {len(self.graded)} calls right."
        teams = [call.team, call.opp] if call.kind == "momentum_xg" else [call.team]
        return Draft("prediction_result", 3, 9000, facts, hint, f"result:{call.kind}:{call.team}:{call.made_s:.1f}", call.team, teams, [])


def _team(st: MatchState, team_id: str) -> str:
    return st.meta.home.name if team_id == st.home_id else st.meta.away.name
