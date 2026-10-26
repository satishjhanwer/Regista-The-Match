"""Analyst agent: reads match state through tools and frames the moment.

Output is a ``Brief``: the insight (plus any candidate facts the Analyst chose
to promote), the ordered fact ids worth telling, and a one-line angle. The Analyst
never writes a number; it selects facts. Without an LLM client a rule-based Analyst
selects the detector's facts in order and uses the detector's rationale as the angle.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ..contracts.insight import Insight
from .context import InsightContext, ToolBox

ANALYST_INSTRUCTIONS = """You are the Analyst in a live football broadcast team.
A detector flagged a moment. Use your tools to understand it and add context that makes it matter:
a player's match stats, a team's recent form in a window, the score and momentum.
Rules:
- Never compute or invent numbers. Every number you want told must be a fact_id from get_facts or from a tool result.
- Pick 2 to 6 fact ids, most important first. Prefer the detector's facts; add at most 2 tool facts.
- The detector_rationale is the verified account of what happened; your angle must agree with it and name the team or player.
- Reply with JSON only: {"fact_ids": ["..."], "angle": "one sentence on why this moment matters, no numbers"}"""


@dataclass
class Brief:
    insight: Insight  # detector facts plus promoted candidate facts
    fact_ids: list[str]
    angle: str
    tool_calls: list[dict]
    source: str  # "llm" or "rules"


def extract_json(text: str) -> dict:
    """First complete JSON object in a model reply. Tolerates code fences, prose, and a second object after it."""
    decoder = json.JSONDecoder()
    for m in re.finditer(r"\{", text):
        try:
            obj, _ = decoder.raw_decode(text, m.start())
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    raise ValueError("no JSON object in reply")


def rule_brief(ctx: InsightContext) -> Brief:
    ins = ctx.insight
    return Brief(ins, [f.fact_id for f in ins.facts], ins.why_it_matters_hint, [], "rules")


def moment_prompt(ins: Insight) -> str:
    return json.dumps(
        {
            "kind": ins.kind,
            "clock": ins.clock.display,
            "detector_rationale": ins.why_it_matters_hint,
            "teams": ins.entities.team_ids,
            "players": ins.entities.player_ids,
        },
        ensure_ascii=False,
    )


class Analyst:
    def __init__(self, client=None) -> None:
        self.client = client

    async def brief(self, ctx: InsightContext) -> Brief:
        if self.client is None:
            return rule_brief(ctx)
        from agent_framework import Agent

        box = ToolBox(ctx)
        agent = Agent(client=self.client, name="Analyst", instructions=ANALYST_INSTRUCTIONS, tools=box.tools())
        reply = await agent.run(f"Moment: {moment_prompt(ctx.insight)}\nCall get_facts first.")
        data = extract_json(reply.text)
        known = {f.fact_id for f in ctx.insight.facts} | set(box.candidates)
        chosen = [fid for fid in dict.fromkeys(data.get("fact_ids", [])) if fid in known]
        if not chosen:
            raise ValueError("Analyst selected no known fact ids")
        promoted = [box.candidates[fid] for fid in chosen if fid in box.candidates]
        insight = ctx.insight.model_copy(update={"facts": [*ctx.insight.facts, *promoted]}) if promoted else ctx.insight
        angle = str(data.get("angle") or ctx.insight.why_it_matters_hint)[:300]
        return Brief(insight, chosen, angle, box.calls, "llm")
