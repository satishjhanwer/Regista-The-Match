"""Match state over MCP: the Analyst's tools, for any agent or MCP client.

The tools are the same code the Analyst uses (``agents.context``), so an outside agent gets the same numbers, with
the same labels and evidence, as Regista's own. Two rules hold for every tool:

- **Live-clock guard.** Answers come from the replay as it stands. A moment the replay has not reached does not
  exist yet, and "now" is never later than the replay position. Inside the API the server reads the shared clock that
  viewers watch, so an agent sees what viewers see, no more.
- **Facts with evidence.** Every number comes back with a label and an evidence window, never as bare prose.

Tools are async on purpose: inside the API they run on the replay's event loop, so they never read state while an
event is half applied.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from ..agents.context import WINDOW_METRICS, InsightContext, ToolBox, capture
from ..api.replay import Replay

INSTRUCTIONS = """Live match intelligence for one synthetic football match (fictional clubs and players).
Everything is as of the replay clock: call `clock` first. Moments are detected insights with facts and evidence;
pass an insight_id to get_state / get_player / get_window_stats to see the match as it was at that moment.
Numbers come from Regista's analytics; quote them with their labels, never compute new ones."""


def _json(x) -> str:
    return json.dumps(x, ensure_ascii=False)


def build_server(get_replay: Callable[[], Replay], *, can_seek: bool = False) -> MCPServer:
    """An MCP server over the replay ``get_replay()`` returns. ``can_seek`` adds a ``seek`` tool (standalone use only)."""
    server = MCPServer(name="regista", title="Regista match intelligence", instructions=INSTRUCTIONS, version="0.3.0")

    def moment(insight_id: str) -> InsightContext | None:
        return next((c for c in get_replay().history if c.insight is not None and c.insight.insight_id == insight_id), None)

    def toolbox(insight_id: str | None) -> ToolBox | str:
        """Tools over a reached moment's snapshot, or over the match right now."""
        if insight_id:
            ctx = moment(insight_id)
            return ToolBox(ctx) if ctx else _json({"error": f"no moment {insight_id} yet (not reached, or unknown)"})
        r = get_replay()
        return ToolBox(capture(r.state, None), prefix=f"{r.match.meta.match_id}-AT-{int(r.clock_s)}")

    @server.tool()
    async def match_info() -> str:
        """Teams and squads: team ids, names, and each player's id, name, position and role."""
        meta = get_replay().match.meta
        teams = [
            {
                "team_id": t.team_id,
                "name": t.name,
                "players": [{"player_id": p.player_id, "name": p.name, "position": p.position, "role": p.role} for p in t.players],
            }
            for t in (meta.home, meta.away)
        ]
        return _json({"match_id": meta.match_id, "venue": meta.venue, "home": teams[0], "away": teams[1]})

    @server.tool()
    async def clock() -> str:
        """The replay clock and score right now. Nothing later than this is visible to any tool."""
        r = get_replay()
        return _json({**r.clock(), "score": dict(r.state.score), "finished": r.finished, "moments_so_far": len(r.history)})

    @server.tool()
    async def list_moments(
        kind: Annotated[str | None, Field(description="Only this kind, e.g. goal, press_change, prediction_result")] = None,
    ) -> str:
        """Moments detected so far, oldest first: insight id, clock, kind, priority and the detector's one-line rationale."""
        out = [
            {"insight_id": i.insight_id, "clock": i.clock.display, "kind": i.kind, "priority": i.priority, "why": i.why_it_matters_hint}
            for i in get_replay().insights
            if kind is None or i.kind == kind
        ]
        return _json(out)

    @server.tool()
    async def get_moment(insight_id: Annotated[str, Field(description="An insight id from list_moments")]) -> str:
        """One moment's facts, each with its label, value, unit, baseline and evidence (event ids or metric windows)."""
        ctx = moment(insight_id)
        if ctx is None:
            return _json({"error": f"no moment {insight_id} yet (not reached, or unknown)"})
        return ctx.insight.model_dump_json()

    @server.tool()
    async def get_state(
        insight_id: Annotated[str | None, Field(description="Omit for now; an insight id for the match as it was then")] = None,
    ) -> str:
        """Score, xG, momentum share, chaos and control scores, as facts with evidence."""
        box = toolbox(insight_id)
        return box if isinstance(box, str) else box.get_state()

    @server.tool()
    async def get_player(
        player_id: Annotated[str, Field(description="Player id, e.g. NVL-09")],
        insight_id: Annotated[str | None, Field(description="Omit for now; an insight id for the match as it was then")] = None,
    ) -> str:
        """A player's profile and match stats: goals, passes, completion, shots, xG, top speed, career totals."""
        box = toolbox(insight_id)
        return box if isinstance(box, str) else box.get_player(player_id)

    @server.tool()
    async def get_window_stats(
        team_id: Annotated[str, Field(description="Team id, e.g. NVL or SLM")],
        metric: Annotated[str, Field(description=f"One of: {', '.join(WINDOW_METRICS)}")],
        window: Annotated[str, Field(description="Rolling window: 5m or 10m")] = "5m",
        insight_id: Annotated[str | None, Field(description="Omit for now; an insight id for the match as it was then")] = None,
    ) -> str:
        """One team metric over the last 5 or 10 minutes."""
        box = toolbox(insight_id)
        return box if isinstance(box, str) else box.get_window_stats(team_id, metric, window)

    @server.tool()
    async def call_record() -> str:
        """Regista's graded calls so far: when each was made, what it was about, and whether it came true."""
        out = []
        for i in get_replay().insights:
            if i.kind != "prediction_result":
                continue
            facts = {f.key: f.value for f in i.facts}
            out.append(
                {
                    "insight_id": i.insight_id,
                    "graded_at": i.clock.display,
                    "made_at": facts.get("prediction.call_made"),
                    "team_id": i.entities.team_ids[0],
                    "result": facts.get("prediction.result"),
                    "why": i.why_it_matters_hint,
                }
            )
        return _json(out)

    if can_seek:

        @server.tool()
        async def seek(
            minute: Annotated[float, Field(description="Match minute 0-90 (stoppage folds into 45 and 90)", ge=0, le=95)],
        ) -> str:
            """Move the replay to a match minute. Moments after it disappear until the replay reaches them again."""
            r = get_replay()
            r.seek(r.elapsed_for_minute(minute))
            return await clock()

    return server
