"""Smoke test: one Agent Framework agent, one function tool, your Foundry model deployment.

Run this tonight. If it prints a grounded answer that uses the tool, the whole
agent stack (auth, endpoint, deployment, tool calling) is proven for Saturday.

    pip install -e ".[agents]"
    az login                      # or set AZURE_OPENAI_API_KEY in .env
    python scripts/hello_foundry.py

Env (.env in /backend or exported). Option A is preferred (Foundry project):
    FOUNDRY_PROJECT_ENDPOINT=https://<resource>.services.ai.azure.com/api/projects/<project>
    FOUNDRY_MODEL=<deployment name>
Option B (plain Azure OpenAI resource):
    AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/
    AZURE_OPENAI_MODEL=<deployment name>
    AZURE_OPENAI_API_KEY=<optional; omit to use az login / managed identity>

Note: if OPENAI_API_KEY is set in your shell, the generic OpenAI client prefers
OpenAI over Azure. Option B always passes an explicit Azure endpoint and
credential, which forces Azure routing.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Annotated

from agent_framework import Agent
from dotenv import load_dotenv
from pydantic import Field

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


def build_client():
    """Foundry project client when FOUNDRY_PROJECT_ENDPOINT is set, else Azure OpenAI."""
    from azure.identity import DefaultAzureCredential

    if os.getenv("FOUNDRY_PROJECT_ENDPOINT"):
        from agent_framework.foundry import FoundryChatClient

        return FoundryChatClient(
            project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
            model=os.environ["FOUNDRY_MODEL"],
            credential=DefaultAzureCredential(),
        )

    from agent_framework.openai import OpenAIChatClient

    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
    model = os.environ["AZURE_OPENAI_MODEL"]
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    if api_key:
        return OpenAIChatClient(api_key=api_key, azure_endpoint=endpoint, model=model)
    return OpenAIChatClient(credential=DefaultAzureCredential(), azure_endpoint=endpoint, model=model)


async def main() -> None:
    load_dotenv()
    if not DATA.exists():
        raise SystemExit("Generate the match first: python -m regista.sim generate --out ../data")
    agent = Agent(
        client=build_client(),
        name="Analyst",
        instructions=("You are a football match analyst. Never state a number you did not get from a tool. Answer in two sentences."),
        tools=[get_score_at],
    )
    result = await agent.run("What was the score at minute 70, and who scored?")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
