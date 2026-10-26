"""Narrator agent: writes one rendering per fan profile, directly in the target language.

The model returns JSON (headline, claims with fact ids, stat callout fact id). The
body is the claims joined, and the stat callout's value is formatted from the fact
by code, so the only free text is prose that the Verifier checks claim by claim.
"""

from __future__ import annotations

import json

from ..contracts.events import MatchMeta
from ..contracts.insight import Claim, FanProfile, RenderedInsight, Verification
from .analyst import Brief, extract_json
from .templates import FactView, stat_callout

LANGUAGE_NAMES = {"en": "English", "es": "Spanish", "hi": "Hindi (Devanagari script; keep player and team names in Latin script)"}

MODE_STYLE = {
    "analyst": "Analyst mode: 2-4 precise sentences, lead with the most technical fact, numbers welcome.",
    "casual": "Casual mode: 1-2 short, lively sentences, at most one number, tell the story not the stats.",
    "player_focus": "Player-focus mode: centre the focus player if involved; otherwise one short sentence.",
}

NARRATOR_INSTRUCTIONS = """You are the Narrator for a live football broadcast overlay.
Write about one moment for one viewer, directly in the requested language (do not translate from English).
Hard rules, checked by a Verifier that rejects violations:
- Every sentence is a claim with the fact_ids it relies on. Every number in a sentence must equal a value or
  previous_value of a cited fact (you may write a 0-1 value as a percentage). Do not round differently.
- A sentence with no fact_ids (fan colour) must contain no numbers.
- Say who every number is about, in the terms of its fact label. "Northvale FC passes under pressure: 64%" means
  64% of Northvale's passes were made under pressure; it is not a completion rate and not about one player.
- The moment's "what_happened" is the detector's verified account. Your story must agree with it.
- Only name players and teams that appear in the facts or entities given.
- headline at most 80 characters; all sentences together at most 320 characters.
Reply with JSON only:
{"headline": "...", "claims": [{"text": "...", "fact_ids": ["..."]}], "stat_callout_fact_id": "... or null"}"""


def narration_prompt(brief: Brief, profile: FanProfile, meta: MatchMeta, feedback: str | None = None) -> str:
    ins = brief.insight
    chosen = set(brief.fact_ids)
    names = {p.player_id: p.short_name for t in (meta.home, meta.away) for p in t.players}
    teams = {t.team_id: t.name for t in (meta.home, meta.away)}
    body = {
        "moment": {"kind": ins.kind, "clock": ins.clock.display, "what_happened": ins.why_it_matters_hint, "angle": brief.angle},
        "viewer": {
            "language": LANGUAGE_NAMES.get(profile.language, profile.language),
            "mode": MODE_STYLE[profile.mode],
            "favorite_team": teams.get(profile.favorite_team_id or ""),
            "focus_player": names.get(profile.focus_player_id or ""),
        },
        "entities": {"teams": [teams[t] for t in ins.entities.team_ids], "players": [names.get(p, p) for p in ins.entities.player_ids]},
        "facts": [
            {"fact_id": f.fact_id, "label": f.label, "value": f.value, "unit": f.unit, "previous_value": f.previous_value}
            for f in ins.facts
            if f.fact_id in chosen
        ],
    }
    text = json.dumps(body, ensure_ascii=False)
    if feedback:
        text += f"\nYour previous draft was rejected by the Verifier:\n{feedback}\nFix every issue and reply with corrected JSON."
    return text


class LLMNarrator:
    def __init__(self, client, meta: MatchMeta) -> None:
        self.client = client
        self.meta = meta

    async def render(self, brief: Brief, profile: FanProfile, feedback: str | None = None) -> RenderedInsight:
        from agent_framework import Agent

        agent = Agent(client=self.client, name="Narrator", instructions=NARRATOR_INSTRUCTIONS)
        reply = await agent.run(narration_prompt(brief, profile, self.meta, feedback))
        return self.parse(reply.text, brief, profile)

    def parse(self, text: str, brief: Brief, profile: FanProfile) -> RenderedInsight:
        data = extract_json(text)
        claims = [Claim(text=str(c["text"]).strip(), fact_ids=[str(x) for x in c.get("fact_ids", [])]) for c in data.get("claims", [])]
        stat = None
        fid = data.get("stat_callout_fact_id")
        fact = next((f for f in brief.insight.facts if f.fact_id == fid), None)
        if fact is not None:
            stat = stat_callout(fact, FactView(brief.insight, self.meta), profile.language)
        return RenderedInsight(
            insight_id=brief.insight.insight_id,
            profile_id=profile.profile_id,
            language=profile.language,
            mode=profile.mode,
            headline=str(data.get("headline", ""))[:80],
            body=" ".join(c.text for c in claims)[:320],
            stat_callout=stat,
            claims=claims,
            verification=Verification(status="pending"),
        )
