"""Match state over MCP, through a real MCP client: the live-clock guard, parity with the Analyst, the API mount."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp.client.client import Client  # noqa: E402
from mcp.client.stdio import StdioServerParameters  # noqa: E402

from regista.agents.context import ToolBox  # noqa: E402
from regista.api.app import create_app  # noqa: E402
from regista.api.replay import Replay  # noqa: E402
from regista.mcp_server import build_server  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]


async def call(client: Client, tool: str, **args):
    res = await client.call_tool(tool, args)
    assert not res.is_error, res
    return json.loads(res.content[0].text)


def at_minute(match, minute: float) -> Replay:
    r = Replay(match)
    r.seek(r.elapsed_for_minute(minute))
    return r


def test_tools_never_see_past_the_replay_clock(sims):
    match, _ = sims[7]
    full = at_minute(match, 95)
    later = next(i for i in full.insights if i.kind == "goal" and i.clock.period == 2)  # the 64' equaliser
    r = at_minute(match, 30)

    async def run():
        async with Client(build_server(lambda: r, can_seek=True)) as c:
            assert (await call(c, "clock"))["display"].startswith("30:")
            seen = await call(c, "list_moments")
            fired_at = {ctx.insight.insight_id: ctx.elapsed_s for ctx in full.history}
            assert seen and all(fired_at[m["insight_id"]] <= r.clock_s for m in seen)
            assert len(seen) == sum(1 for s in fired_at.values() if s <= r.clock_s)
            assert later.insight_id not in {m["insight_id"] for m in seen}
            assert "error" in await call(c, "get_moment", insight_id=later.insight_id)
            assert "error" in await call(c, "get_state", insight_id=later.insight_id)
            assert (await call(c, "clock"))["score"] == {"NVL": 0, "SLM": 0}

            await call(c, "seek", minute=70)
            goal = await call(c, "get_moment", insight_id=later.insight_id)
            assert goal["kind"] == "goal" and goal["facts"]
            assert (await call(c, "clock"))["score"] == {"NVL": 1, "SLM": 1}

            await call(c, "seek", minute=30)  # back again: the goal has not happened yet
            assert "error" in await call(c, "get_moment", insight_id=later.insight_id)

    asyncio.run(run())


def test_same_numbers_as_the_analyst(sims):
    match, _ = sims[7]
    r = at_minute(match, 65)
    ctx = next(c for c in r.history if c.insight.kind == "press_change")

    async def run():
        async with Client(build_server(lambda: r)) as c:
            names = [t.name for t in (await c.list_tools()).tools]
            assert "seek" not in names  # read-only unless asked for
            assert await call(c, "get_state", insight_id=ctx.insight.insight_id) == json.loads(ToolBox(ctx).get_state())
            ws = await call(c, "get_window_stats", team_id="NVL", metric="pass_completion", window="5m", insight_id=ctx.insight.insight_id)
            assert ws == json.loads(ToolBox(ctx).get_window_stats("NVL", "pass_completion", "5m"))
            now = await call(c, "get_player", player_id="SLM-09")
            assert any(s["label"] == "Shapira goals this match" and s["value"] == 1 for s in now["stats"])
            assert all(s["fact_id"].startswith("RGS-2026-0001-AT-") for s in now["stats"])
            assert "error" in await call(c, "get_player", player_id="XXX-99")

    asyncio.run(run())


def test_call_record_matches_the_graded_calls(sims):
    match, _ = sims[7]
    r = at_minute(match, 95)
    results = [i for i in r.insights if i.kind == "prediction_result"]

    async def run():
        async with Client(build_server(lambda: r)) as c:
            record = await call(c, "call_record")
            assert [x["insight_id"] for x in record] == [i.insight_id for i in results]
            assert {x["result"] for x in record} <= {"right", "wrong"}

    asyncio.run(run())


def test_standalone_server_over_stdio():
    params = StdioServerParameters(command=sys.executable, args=["-m", "regista.mcp_server", "--minute", "62"], cwd=str(BACKEND))

    async def run():
        async with Client(params) as c:
            assert "seek" in [t.name for t in (await c.list_tools()).tools]
            assert (await call(c, "clock"))["display"].startswith("62:")
            info = await call(c, "match_info")
            assert info["home"]["name"] == "Northvale FC" and info["away"]["team_id"] == "SLM"

    asyncio.run(run())


def test_api_serves_it_read_only_on_the_shared_clock(sims):
    from fastapi.testclient import TestClient

    match, _ = sims[7]
    app = create_app(match, client=None, autoplay=False)
    with TestClient(app) as http:
        http.post("/api/replay", json={"action": "seek", "minute": 66})

        async def run():
            async with Client(app.state.mcp) as c:
                assert "seek" not in [t.name for t in (await c.list_tools()).tools]
                clock = await call(c, "clock")
                assert clock["display"] == http.get("/api/replay").json()["clock"]["display"]
                assert clock["score"] == {"NVL": 1, "SLM": 1}

        asyncio.run(run())
        assert any(getattr(route, "path", "") == "/mcp" for route in app.routes)
