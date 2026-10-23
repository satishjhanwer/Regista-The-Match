"""Half-time and full-time recap, built from the insights accumulated so far.

The recap is itself an Insight (kind "recap"), so it goes through the same
Narrator and Verifier path. Its facts are copied from earlier insights together
with their evidence, so the recap's claims trace back to the original events.
"""

from __future__ import annotations

from ..contracts.events import MatchMeta
from ..contracts.insight import Entities, Fact, Insight


def _find(ins: Insight, key: str) -> Fact | None:
    return next((f for f in ins.facts if f.key == key), None)


def build_recap(meta: MatchMeta, insights: list[Insight], summary: Insight) -> Insight:
    """Recap for the period that ``summary`` (a period_summary insight) closes."""
    rid = f"{meta.match_id}-RECAP-{summary.clock.period}"
    facts: list[Fact] = []
    players: list[str] = []
    short = {t.team_id: t.short_name for t in (meta.home, meta.away)}

    def add(key: str, label: str, value, evidence, unit=None, previous=None) -> None:
        facts.append(
            Fact(
                fact_id=f"{rid}-F{len(facts) + 1}",
                key=key,
                label=label,
                value=value,
                unit=unit,
                previous_value=previous,
                evidence=list(evidence),
            )
        )

    if (score := _find(summary, "match.score")) is not None:
        add("match.score", score.label, score.value, score.evidence)
    upto = [i for i in insights if i.created_at <= summary.created_at]
    goals = [i for i in upto if i.kind == "goal"]
    for n, g in enumerate(goals, 1):
        scorer = _find(g, "goal.scorer")
        team = g.entities.team_ids[0]
        add(f"recap.goal{n}", f"Goal {n}", f"{g.clock.display} {scorer.value} ({short[team]})", scorer.evidence)
        players.append(g.entities.player_ids[0])
    for team in (meta.home.team_id, meta.away.team_id):
        press = next((i for i in upto if i.kind == "press_change" and i.entities.team_ids == [team]), None)
        if press is not None and (start := _find(press, f"{team}.press_change_start")) is not None:
            add(f"{team}.recap_press_start", f"{start.label} ({short[team]})", start.value, start.evidence)
    chaos = next((i for i in upto if i.kind == "control_vs_chaos" and not i.entities.team_ids), None)
    if chaos is not None and (c := _find(chaos, "match.chaos_5m")) is not None:
        add("recap.chaos_start", "Chaotic spell began", chaos.clock.display, c.evidence)
    for m in (i for i in upto if i.kind == "milestone"):
        pid = m.entities.player_ids[0]
        if (cg := _find(m, f"{pid}.career_goals")) is not None:
            add(cg.key, cg.label, cg.value, cg.evidence, cg.unit, cg.previous_value)
            players.append(pid)
    for team in (meta.home.team_id, meta.away.team_id):
        for key in (f"{team}.xg_total", f"{team}.shots"):
            if (f := _find(summary, key)) is not None:
                add(key, f.label, f.value, f.evidence, f.unit)

    label = "Half-time" if summary.clock.period == 1 else "Full-time"
    hint = f"{label} recap: " + "; ".join(str(f.value) for f in facts if f.key.startswith("recap.goal")) + "."
    return Insight(
        insight_id=rid,
        match_id=meta.match_id,
        kind="recap",
        priority=4,
        clock=summary.clock,
        created_at=summary.created_at,
        ttl_ms=20000,
        entities=Entities(team_ids=[meta.home.team_id, meta.away.team_id], player_ids=list(dict.fromkeys(players))),
        facts=facts,
        why_it_matters_hint=hint,
    )
