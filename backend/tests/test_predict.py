"""Calls and their grading: every verdict re-derived from raw events, detector ids untouched, voids, the Verifier."""

from __future__ import annotations

import pytest

from regista.agents.profiles import PRESETS
from regista.agents.templates import TemplateNarrator
from regista.agents.verifier import Verifier
from regista.detect import InsightPipeline
from regista.detect.predict import CALL_KINDS, HORIZON_S, MIN_SPAN_S, Predictor, load_base_rates

SEEDS = [1, 2, 3, 4, 5, 7]


class Silent(Predictor):
    def step(self, ev, new_kinds, st):
        return []


def run(match, predictor=None):
    pipe = InsightPipeline(match.meta, predictor=predictor)
    for ev in match.events:
        pipe.process(ev)
    return pipe


def facts(ins) -> dict:
    """Facts by key, with team ids replaced by team. / opp. relative to the insight's first team."""
    team = ins.entities.team_ids[0]
    out = {}
    for f in ins.facts:
        prefix, _, rest = f.key.partition(".")
        out[f.key if prefix not in ("NVL", "SLM") else ("team." if prefix == team else "opp.") + rest] = f
    return out


@pytest.mark.parametrize("seed", SEEDS)
def test_every_verdict_matches_the_raw_events(sims, seed):
    match, _ = sims[seed]
    pipe = run(match)
    calls = {i.insight_id: i for i in pipe.insights if i.kind == "prediction"}
    results = [i for i in pipe.insights if i.kind == "prediction_result"]
    assert calls and results
    shots = [e for e in match.events if e.type == "shot"]
    passes = [e for e in match.events if e.type == "pass"]
    made_at = {(i.clock.display, i.entities.team_ids[0]): i for i in calls.values()}
    for res in results:
        f = facts(res)
        team = res.entities.team_ids[0]
        call = made_at[(f["prediction.call_made"].value, team)]
        lo = call.facts[0].evidence[0].window_start_s
        hi = res.created_at.timestamp() - pipe.kickoff.timestamp()
        assert MIN_SPAN_S <= hi - lo <= HORIZON_S + 60
        if "team.xg_since_call" in f:
            opp = res.entities.team_ids[1]
            xg = {t: sum(pipe.state.shot_xg[s.event_id] for s in shots if s.team_id == t and lo < s.elapsed_s <= hi) for t in (team, opp)}
            assert f["team.xg_since_call"].value == round(xg[team], 2)
            assert f["opp.xg_since_call"].value == round(xg[opp], 2)
            right = round(xg[team], 2) > round(xg[opp], 2)
        else:
            mine = [p for p in passes if p.team_id == team and lo < p.elapsed_s <= hi]
            comp = round(100 * sum(p.outcome == "complete" for p in mine) / len(mine))
            assert f["team.pass_completion_since_call"].value == comp
            right = comp < f["team.pass_completion_since_call"].previous_value
        assert f["prediction.result"].value == ("right" if right else "wrong")


@pytest.mark.parametrize("seed", SEEDS)
def test_calls_never_renumber_the_detector_insights(sims, seed):
    match, _ = sims[seed]
    with_calls = [i for i in run(match).insights if "-INS-" in i.insight_id]
    without = [i for i in run(match, Silent()).insights if "-INS-" in i.insight_id]
    assert [i.model_dump() for i in with_calls] == [i.model_dump() for i in without]


@pytest.mark.parametrize("seed", SEEDS)
def test_record_and_voids(sims, seed):
    match, _ = sims[seed]
    predictor = Predictor()
    pipe = run(match, predictor)
    calls = [i for i in pipe.insights if i.kind == "prediction"]
    results = [i for i in pipe.insights if i.kind == "prediction_result"]
    ends = [e.elapsed_s for e in match.events if e.type == "period_end"]
    graded = {(facts(r)["prediction.call_made"].value, r.entities.team_ids[0]) for r in results}
    for c in calls:
        if (c.clock.display, c.entities.team_ids[0]) not in graded:  # void: the half ended less than 5 minutes later
            made = c.facts[0].evidence[0].window_start_s
            assert any(0 <= end - made < MIN_SPAN_S for end in ends), c.clock.display
    records = [(facts(r)["prediction.calls_right"].value, facts(r)["prediction.calls_graded"].value) for r in results]
    assert [g for _, g in records] == list(range(1, len(results) + 1))
    assert records[-1][0] == sum(right for _, right in predictor.graded)


def test_stated_chance_is_the_fitted_rate(sims):
    rates = load_base_rates()
    assert set(rates) == set(CALL_KINDS) and all(0 < r["p"] < 1 and r["n"] > 0 for r in rates.values())
    match, _ = sims[7]
    for call in (i for i in run(match).insights if i.kind == "prediction"):
        kind = "momentum_xg" if any(f.key.endswith(".xg_total") for f in call.facts) else "press_completion"
        f = facts(call)
        assert f["prediction.probability"].value == round(100 * rates[kind]["p"])
        assert f["prediction.sample"].value == rates[kind]["n"]


def test_no_rates_means_no_stated_chance(sims):
    match, _ = sims[7]
    calls = [i for i in run(match, Predictor(base_rates={})).insights if i.kind == "prediction"]
    assert calls and not any(f.key == "prediction.probability" for c in calls for f in c.facts)


def test_the_verifier_rejects_a_flipped_verdict(sims):
    match, _ = sims[7]
    res = next(i for i in run(match).insights if i.kind == "prediction_result")
    verdict = facts(res)["prediction.result"].value
    flipped = res.model_copy(
        update={
            "facts": [
                f.model_copy(update={"value": "wrong" if verdict == "right" else "right"}) if f.key == "prediction.result" else f
                for f in res.facts
            ]
        }
    )
    tn, v = TemplateNarrator(match.meta), Verifier(match.meta)
    for p in PRESETS.values():
        assert v.verify(tn.render(res, p), res).ok
        lie = tn.render(flipped, p)  # the opposite verdict, citing the real facts
        report = v.verify(lie, res)
        assert not report.ok and any("but the facts say" in n for n in report.verification.notes), (p.profile_id, lie.body)
