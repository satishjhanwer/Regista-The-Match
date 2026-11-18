"""A whole match narrated by a model that lies on every draft: nothing it writes may reach the screen.

The Narrator below starts from a verified template rendering, then corrupts it the way real models did
(D28): an inflated number, a fact id that does not exist, a stranger's name, a number with no citation,
the wrong language, a team swap, a number in the wrong unit, a placeholder, an overlong draft. The Analyst model misbehaves too
(invented fact ids, prose instead of JSON). Every draft still goes through the real ``LLMNarrator.parse``,
the real Verifier and the real WarmPath retry and fallback, over every insight of the demo match for
every preset profile.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import pytest
from fake_llm import ScriptedClient

from regista.agents.context import capture
from regista.agents.narrator import LLMNarrator
from regista.agents.orchestrator import WarmPath
from regista.agents.profiles import PRESETS
from regista.agents.templates import TemplateNarrator
from regista.agents.verifier import Verifier
from regista.detect import InsightPipeline

ROOT = Path(__file__).resolve().parents[2]
TEAM_SWAP = {"Northvale FC": "Saltmere Athletic", "Saltmere Athletic": "Northvale FC", "Northvale": "Saltmere", "Saltmere": "Northvale"}
OTHER_LANGUAGE = {"en": "hi", "es": "hi", "hi": "en"}
LIES = {"flip_verdict", "inflate", "phantom_fact", "stranger", "uncited_number", "wrong_language", "team_swap", "unit_swap"}
LIES |= {"placeholder", "overlong"}
# A measured number with its unit, and the count noun a lie swaps in for it ("34.8 km/h" -> "34.8 goals").
UNIT = re.compile(r"(\d+(?:[.,]\d+)?)\s*(km/h|%|xG|metros|metres|मीटर|minutes|minutos|मिनट|m)(?![\w/])")
GOALS = {"en": "goals", "es": "goles", "hi": "गोल"}


def _rule_of():
    spec = importlib.util.spec_from_file_location("eval_run", ROOT / "backend" / "scripts" / "eval_run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.rule_of


@pytest.fixture(scope="module")
def seed7(sims):
    match, _ = sims[7]
    pipe = InsightPipeline(match.meta)
    contexts = []
    for ev in match.events:
        contexts += [capture(pipe.state, ins) for ins in pipe.process(ev)]
    return match, contexts


def _digits(text: str) -> bool:
    return re.search(r"\d", text) is not None


class LyingNarrator(LLMNarrator):
    """Corrupts a verified template draft, a different lie on every call, and parses it like a model reply."""

    def __init__(self, meta, *, lie: bool = True) -> None:
        super().__init__(None, meta)
        self.templates = TemplateNarrator(meta)
        self.lie = lie
        self.calls = 0
        self.told: dict[str, list[str]] = defaultdict(list)  # lie kind -> profile ids it was told to
        names = {t.team_id: t for t in (meta.home, meta.away)}
        self.roster = [p for t in names.values() for p in t.players]

    async def render(self, brief, profile, feedback=None):
        """One draft as model JSON, then the real parser (which raises DraftShapeError when too long)."""
        honest = self.templates.render(brief.insight, profile)
        draft = {
            "headline": honest.headline,
            "claims": [{"text": c.text, "fact_ids": list(c.fact_ids)} for c in honest.claims],
            "stat_callout_fact_id": None,
        }
        if self.lie:
            # A graded call is first told with the opposite verdict, then lied about the usual ways.
            first = feedback is None and self._flip_verdict(draft, brief, profile)
            kind = "flip_verdict" if first else self._corrupt(draft, brief, profile)
            self.told[kind].append(profile.profile_id)
        self.calls += 1
        return self.parse(json.dumps(draft, ensure_ascii=False), brief, profile)

    def _corrupt(self, draft, brief, profile) -> str:
        lies = [self._inflate, self._phantom_fact, self._stranger, self._uncited_number, self._wrong_language, self._team_swap]
        lies += [self._unit_swap, self._placeholder, self._overlong]
        for i in range(len(lies)):
            lie = lies[(self.calls + i) % len(lies)]
            if lie(draft, brief, profile):
                return lie.__name__.lstrip("_")
        raise AssertionError("no lie applies")  # _placeholder always applies

    def _flip_verdict(self, draft, brief, profile) -> bool:
        ins = brief.insight
        if ins.kind != "prediction_result":
            return False
        flip = {"right": "wrong", "wrong": "right"}
        flipped = ins.model_copy(
            update={"facts": [f.model_copy(update={"value": flip[f.value]}) if f.key == "prediction.result" else f for f in ins.facts]}
        )
        lie = self.templates.render(flipped, profile)
        draft["headline"] = lie.headline
        draft["claims"] = [{"text": c.text, "fact_ids": list(c.fact_ids)} for c in lie.claims]
        return True

    def _inflate(self, draft, brief, profile) -> bool:
        for c in draft["claims"]:
            if c["fact_ids"] and _digits(c["text"]):
                c["text"] = re.sub(r"\d+", lambda m: str(int(m.group()) + 7), c["text"], count=1)
                return True
        return False

    def _phantom_fact(self, draft, brief, profile) -> bool:
        draft["claims"][0]["fact_ids"].append("F99")
        return True

    def _stranger(self, draft, brief, profile) -> bool:
        involved = set(brief.insight.entities.player_ids)
        stranger = next(p for p in self.roster if p.player_id not in involved)
        draft["claims"][0]["text"] = f"{stranger.short_name}: {draft['claims'][0]['text']}"
        return True

    def _uncited_number(self, draft, brief, profile) -> bool:
        cited = next((c for c in draft["claims"] if c["fact_ids"] and _digits(c["text"])), None)
        if cited is None:
            return False
        draft["claims"].append({"text": cited["text"], "fact_ids": []})
        return True

    def _wrong_language(self, draft, brief, profile) -> bool:
        other = self.templates.render(brief.insight, profile.model_copy(update={"language": OTHER_LANGUAGE[profile.language]}))
        draft["claims"] = [{"text": c.text, "fact_ids": list(c.fact_ids)} for c in other.claims]
        return True

    def _team_swap(self, draft, brief, profile) -> bool:
        """Credit one team's numbers to the other. Only claims naming a single team: a role reversal that keeps
        both names is a known limit (see test_role_reversal_is_a_known_limit)."""
        pattern = re.compile("|".join(sorted(map(re.escape, TEAM_SWAP), key=len, reverse=True)))
        swapped = False
        for c in draft["claims"]:
            clubs = {m.group().split()[0] for m in pattern.finditer(c["text"])}
            if c["fact_ids"] and len(clubs) == 1:
                c["text"] = pattern.sub(lambda m: TEAM_SWAP[m.group()], c["text"])
                swapped = True
        return swapped

    def _unit_swap(self, draft, brief, profile) -> bool:
        """Keep the right number, give it the wrong unit."""
        for c in draft["claims"]:
            if c["fact_ids"] and UNIT.search(c["text"]):
                c["text"] = UNIT.sub(lambda m: f"{m.group(1)} {GOALS[profile.language]}", c["text"], count=1)
                return True
        return False

    def _placeholder(self, draft, brief, profile) -> bool:
        draft["headline"] = "<your headline, max 80 characters>"
        return True

    def _overlong(self, draft, brief, profile) -> bool:
        text = draft["claims"][0]["text"]
        draft["claims"][0]["text"] = " ".join([text] * (1 + 330 // len(text)))
        return True


def analyst_responder(messages):
    """Per moment, one of: honest (get_facts, then pick a fact), invented fact ids, or prose instead of JSON."""
    prompt = next(c.text for m in messages for c in m.contents if getattr(c, "text", None))
    style = int(hashlib.sha1(prompt.encode()).hexdigest(), 16) % 3
    results = [str(c.result) for m in messages for c in m.contents if c.type == "function_result"]
    if style == 0:
        if not results:
            return {"call": "get_facts"}
        return json.dumps({"fact_ids": [json.loads(results[0])[0]["fact_id"]], "angle": "This changes the game."})
    if style == 1:
        return json.dumps({"fact_ids": ["RGS-2026-0001-INS-9999-F1"], "angle": "Trust me."})
    return "This is clearly the most important moment of the season."


def narrate_match(match, contexts, narrator) -> list:
    client = ScriptedClient(lambda agent, messages: analyst_responder(messages))
    warm = WarmPath(match.meta, client, narrator=narrator, timeout_s=10)

    async def run():
        return await asyncio.gather(*(warm.render(ctx, p) for ctx in contexts for p in PRESETS.values()))

    return asyncio.run(run())


def test_nothing_a_lying_model_writes_reaches_the_screen(seed7, monkeypatch):
    monkeypatch.delenv("REGISTA_LLM_LANGUAGES", raising=False)
    match, contexts = seed7
    liar = LyingNarrator(match.meta)
    results = narrate_match(match, contexts, liar)
    verifier = Verifier(match.meta)

    assert len(results) == len(contexts) * len(PRESETS) >= 150
    assert liar.calls == 2 * len(results)  # every render: a draft, a rejection, a retry, a second rejection
    assert Counter(r.source for r in results) == {"template_fallback": len(results)}
    for r in results:
        assert verifier.verify(r.rendered, r.insight).ok, (r.rendered.insight_id, r.rendered.profile_id)
        assert r.rendered.verification.status == "verified"
        rejected = [s for s in r.trace if s.agent == "verifier" and s.status == "rejected"]
        assert len(rejected) == 2

    # Every kind of lie was told many times, and every language met nearly all of them (Hindi templates rarely
    # name exactly one team, so the team swap seldom applies there).
    assert set(liar.told) == LIES
    assert all(len(told) >= 10 for told in liar.told.values()), {k: len(v) for k, v in liar.told.items()}
    for lang in ("en", "es", "hi"):
        kinds = {k for k, told in liar.told.items() if any(PRESETS[p].language == lang for p in told)}
        assert len(kinds) >= 7, (lang, kinds)
    rule_of = _rule_of()
    rules = Counter(rule_of(n) for r in results for s in r.trace if s.status == "rejected" for n in s.detail["notes"])
    for rule in (
        "number not in a cited fact",
        "unknown fact id",
        "names someone not in the moment",
        "wrong language or script",
        "placeholder or empty text",
        "too long for the overlay",
        "wrong pass type, finish or call verdict",
        "number in the wrong unit",
    ):
        assert rules[rule] > 0, rules
    assert rules["other"] == 0, rules

    # The misbehaving Analyst fell back to the rule-based brief, and its honest moments still promoted nothing false.
    analyst = Counter(r.trace[0].status for r in results)
    assert analyst["fallback"] > 0 and analyst["ok"] > 0


def test_an_honest_model_airs(seed7, monkeypatch):
    """Control: the same harness without lies puts model drafts on air, so the test above is not rejecting everything."""
    monkeypatch.delenv("REGISTA_LLM_LANGUAGES", raising=False)
    match, contexts = seed7
    results = narrate_match(match, contexts, LyingNarrator(match.meta, lie=False))
    assert Counter(r.source for r in results) == {"llm": len(results)}


@pytest.mark.xfail(strict=True, reason="a role reversal that names both teams is not caught mechanically (D28)")
def test_role_reversal_is_a_known_limit(seed7):
    match, contexts = seed7
    ctx = next(c for c in contexts if c.insight.kind == "press_change")
    nvl, slm = (f for f in ctx.insight.facts[:2])
    honest = TemplateNarrator(match.meta).render(ctx.insight, PRESETS["analyst-en"])
    claim = honest.claims[0].model_copy(update={"text": "Northvale FC are pressing high and Saltmere Athletic are rattled."})
    reversed_ = honest.model_copy(update={"claims": [claim], "body": claim.text})
    assert nvl.label.startswith("Northvale FC") and slm.label.startswith("Saltmere Athletic")
    assert not Verifier(match.meta).verify(reversed_, ctx.insight).ok
