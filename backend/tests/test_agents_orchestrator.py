"""Warm path through the real Agent Framework loop, driven by a scripted model.

Covers: Analyst tool calls and fact promotion, Verifier rejection and Narrator revision,
template fallback on errors, single-flight analysis, caching, recap.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fake_llm import ScriptedClient, message_texts

from regista.agents.context import ToolBox, capture
from regista.agents.orchestrator import WarmPath
from regista.agents.profiles import PRESETS
from regista.agents.recap import build_recap
from regista.agents.templates import TemplateNarrator
from regista.agents.verifier import Verifier
from regista.detect import InsightPipeline


@pytest.fixture(scope="module")
def seed7(sims):
    match, _ = sims[7]
    pipe = InsightPipeline(match.meta)
    contexts = {}
    for ev in match.events:
        for ins in pipe.process(ev):
            contexts[ins.insight_id] = capture(pipe.state, ins)
    return match, pipe.insights, contexts


def first(insights, kind):
    return next(i for i in insights if i.kind == kind)


def tool_results(messages) -> list[str]:
    return [str(c.result) for m in messages for c in m.contents if c.type == "function_result"]


def analyst_script(messages):
    """get_facts -> get_window_stats(NVL long-ball share, 10m) -> select the first detector fact and the tool fact."""
    results = tool_results(messages)
    if len(results) == 0:
        return {"call": "get_facts"}
    if len(results) == 1:
        return {"call": "get_window_stats", "args": {"team_id": "NVL", "metric": "long_ball_share", "window": "10m"}}
    facts, cand = json.loads(results[0]), json.loads(results[1])
    return json.dumps({"fact_ids": [facts[0]["fact_id"], cand["fact_id"]], "angle": "The press is forcing Northvale long."})


class Narration:
    """Narrator script: first draft inflates a number, the revision fixes it."""

    def __init__(self, wrong_first: bool = True) -> None:
        self.calls = 0
        self.wrong_first = wrong_first

    def __call__(self, messages):
        self.calls += 1
        prompt = message_texts(messages)[-1]
        body = json.loads(prompt.split("\n")[0])
        f = body["facts"]
        share = f[0]["value"] + (9 if self.wrong_first and self.calls == 1 else 0)
        claims = [
            {
                "text": f"Northvale now play {share}% of passes under pressure, up from {f[0]['previous_value']}%.",
                "fact_ids": [f[0]["fact_id"]],
            },
            {"text": f"Their long-ball share is {f[1]['value']}% over the last 10 minutes.", "fact_ids": [f[1]["fact_id"]]},
            {"text": "Saltmere smell blood.", "fact_ids": []},
        ]
        return json.dumps({"headline": "Saltmere squeeze Northvale", "claims": claims, "stat_callout_fact_id": f[0]["fact_id"]})


def client_for(narration, analyst=analyst_script):
    return ScriptedClient(lambda agent, messages: analyst(messages) if agent == "Analyst" else narration(messages))


def run(coro):
    return asyncio.run(coro)


def test_llm_path_rejects_then_revises(seed7):
    match, insights, contexts = seed7
    ins = first(insights, "press_change")
    narration = Narration()
    wp = WarmPath(match.meta, client_for(narration))
    res = run(wp.render(contexts[ins.insight_id], PRESETS["analyst-en"]))
    assert res.source == "llm_revised"
    assert res.rendered.verification.status == "revised"
    assert "64%" in res.rendered.body and narration.calls == 2
    steps = [(s.agent, s.status) for s in res.trace]
    assert steps == [("analyst", "ok"), ("narrator", "ok"), ("verifier", "rejected"), ("narrator", "ok"), ("verifier", "ok")]
    assert "number 73" in " ".join(res.trace[2].detail["notes"])
    assert [c["tool"] for c in res.trace[0].detail["tool_calls"]] == ["get_facts", "get_window_stats"]
    promoted = res.insight.facts[-1]
    assert promoted.key == "NVL.long_ball_share_10m" and promoted.evidence[0].kind == "metric"
    assert promoted.evidence[0].window_end_s - promoted.evidence[0].window_start_s == pytest.approx(600, abs=1)
    assert Verifier(match.meta).verify(res.rendered, res.insight).ok


def test_narrator_error_falls_back_to_verified_template(seed7):
    match, insights, contexts = seed7
    ins = first(insights, "goal")

    def boom(messages):
        raise RuntimeError("model unavailable")

    wp = WarmPath(match.meta, client_for(boom))
    res = run(wp.render(contexts[ins.insight_id], PRESETS["casual-es-slm"]))
    assert res.source == "template_fallback" and res.rendered.verification.status == "verified"
    assert res.rendered.language == "es" and res.rendered.headline.startswith("¡GOL!")
    assert [s.agent for s in res.trace][-2:] == ["template", "verifier"]


def test_two_rejections_fall_back(seed7):
    match, insights, contexts = seed7
    ins = first(insights, "press_change")

    def always_wrong(messages):
        f = json.loads(message_texts(messages)[-1].split("\n")[0])["facts"]
        return json.dumps({"headline": "x", "claims": [{"text": "It is 99%.", "fact_ids": [f[0]["fact_id"]]}]})

    res = run(WarmPath(match.meta, client_for(always_wrong)).render(contexts[ins.insight_id], PRESETS["analyst-en"]))
    assert res.source == "template_fallback"
    assert [s.status for s in res.trace if s.agent == "verifier"] == ["rejected", "rejected", "ok"]


def test_bad_analyst_reply_uses_rule_brief(seed7):
    match, insights, contexts = seed7
    ins = first(insights, "milestone")
    res = run(
        WarmPath(match.meta, client_for(Narration(), analyst=lambda m: "no json here")).render(
            contexts[ins.insight_id], PRESETS["analyst-en"]
        )
    )
    assert res.trace[0].status == "fallback" and "JSON" in res.trace[0].detail["error"]
    assert res.rendered.verification.status == "verified"


def test_single_flight_analysis_and_cache(seed7, tmp_path):
    match, insights, contexts = seed7
    ins = first(insights, "press_change")
    client = client_for(Narration(wrong_first=False))
    wp = WarmPath(match.meta, client)
    ctx = contexts[ins.insight_id]

    async def both():
        return await asyncio.gather(wp.render(ctx, PRESETS["analyst-en"]), wp.render(ctx, PRESETS["analyst-es"]))

    a, b = run(both())
    assert sum(1 for agent, _ in client.turns if agent == "Analyst") == 3  # one analysis: 2 tool turns + answer
    assert a.rendered.profile_id != b.rendered.profile_id
    assert run(wp.render(ctx, PRESETS["analyst-en"])) is a
    path = tmp_path / "cache.json"
    wp.save_cache(path)
    loaded = WarmPath.load_cache(path)
    hit = loaded[(ins.insight_id, "analyst-en")]
    assert hit.rendered == a.rendered and hit.trace[0].agent == "cache"


def test_template_only_warm_path(seed7):
    match, insights, contexts = seed7
    wp = WarmPath(match.meta)
    for ins in insights:
        res = run(wp.render(contexts[ins.insight_id], PRESETS["focus-hi-nvl09"]))
        assert res.source == "template" and res.rendered.verification.status == "verified", ins.kind


def test_tools_register_candidates(seed7):
    _, insights, contexts = seed7
    box = ToolBox(contexts[first(insights, "goal").insight_id])
    player = json.loads(box.get_player("NVL-09"))
    assert player["name"] == "Dario Vukovic" and any(s["value"] == 48 for s in player["stats"])
    assert "error" in json.loads(box.get_player("XXX-01"))
    assert "error" in json.loads(box.get_window_stats("NVL", "nonsense", "5m"))
    state = json.loads(box.get_state())
    goals = {s["label"]: s["value"] for s in state if s["label"].endswith(" goals")}
    assert goals == {"Northvale FC goals": 1, "Saltmere Athletic goals": 0}
    assert all(f.evidence for f in box.candidates.values())
    assert len(box.calls) == 4


def test_recap_is_grounded_in_earlier_insights(seed7):
    match, insights, _ = seed7
    summary = [i for i in insights if i.kind == "period_summary"][-1]
    recap = build_recap(match.meta, insights, summary)
    keys = [f.key for f in recap.facts]
    assert keys[:4] == ["match.score", "recap.goal1", "recap.goal2", "recap.goal3"]
    assert "SLM.recap_press_start" in keys and "recap.chaos_start" in keys and "NVL-09.career_goals" in keys
    ids = {e.event_id for e in match.events}
    assert all(f.evidence and all(r.ref in ids for r in f.evidence if r.kind == "event") for f in recap.facts)
    narrator, verifier = TemplateNarrator(match.meta), Verifier(match.meta)
    for profile in PRESETS.values():
        r = narrator.render(recap, profile)
        assert verifier.verify(r, recap).ok, (profile.profile_id, r.body)
    half = build_recap(match.meta, insights, [i for i in insights if i.kind == "period_summary"][0])
    assert [f.key for f in half.facts if f.key.startswith("recap.goal")] == ["recap.goal1"]
