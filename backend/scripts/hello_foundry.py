"""Smoke test: one Agent Framework agent, one function tool, your Foundry model deployment.

Proves auth, endpoint, model and tool calling for whichever provider
backend/.env configures (see regista/llm.py and .env.example).

    pip install -e ".[agents]"
    python scripts/hello_foundry.py

Expected: the score at minute 70 is 1-1, naming Vukovic and Shapira.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

from agent_framework import Agent
from dotenv import load_dotenv
from pydantic import Field

from regista.llm import build_chat_client, resolve_provider

DATA = Path(__file__).resolve().parents[2] / "data" / "RGS-2026-0001.json"


def get_score_at(
    minute: Annotated[int, Field(description="Match minute, 0 to 95")],
) -> str:
    """Return the scoreline and goal list at a given match minute, from the synthetic match file."""
    match = json.loads(DATA.read_text(encoding="utf-8"))
    home, away = match["meta"]["home"]["team_id"], match["meta"]["away"]["team_id"]
    names = {p["player_id"]: p["name"] for t in ("home", "away") for p in match["meta"][t]["players"]}
    goals = [e for e in match["events"] if e["type"] == "shot" and e["outcome"] == "goal" and e["match_clock_s"] <= minute * 60]
    score = {home: 0, away: 0}
    for g in goals:
        score[g["team_id"]] += 1
    return json.dumps(
        {
            "minute": minute,
            "score": score,
            "goals": [{"clock_s": g["match_clock_s"], "team": g["team_id"], "scorer": names[g["player_id"]]} for g in goals],
        }
    )


async def main() -> None:
    """Run one tool-calling question against the configured provider."""
    load_dotenv()
    if not DATA.exists():
        raise SystemExit("Generate the match first: python -m regista.sim generate --out ../data")
    provider = resolve_provider()
    client = build_chat_client(provider)
    if client is None:
        raise SystemExit("No LLM configured. Fill one provider in backend/.env (see .env.example).")
    print(f"provider: {provider}")
    agent = Agent(
        client=client,
        name="Analyst",
        instructions=("You are a football match analyst. Never state a number you did not get from a tool. Answer in two sentences."),
        tools=[get_score_at],
    )
    result = await agent.run("What was the score at minute 70, and who scored?")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
