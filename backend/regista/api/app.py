"""FastAPI app: replay control, insights, on-demand renders and the overlay WebSocket.

    uvicorn regista.api.app:app --reload        # or: python -m regista.api

Environment:
    REGISTA_MATCH         match file (default ../data/RGS-2026-0001.json relative to backend/)
    REGISTA_AGENT_CACHE   recorded warm-path run to serve (python -m regista.agents record ...)
    REGISTA_SPEED         replay speed, match seconds per wall second (default 10)
    REGISTA_AUTOPLAY      1 to start playing on boot (default 1)
    REGISTA_CORS_ORIGINS  comma-separated origins (default *)
    REGISTA_STATIC        built frontend to serve at / (default ../frontend/dist when it exists)
    + the LLM provider variables in regista/llm.py (none configured = template Narrator)
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from ..agents.orchestrator import WarmPath
from ..agents.profiles import PRESETS, profile_from_params
from ..contracts.events import MatchFile
from ..contracts.stream import ControlRequest, ErrorMessage, MomentumPoint, RenderResponse, ReplayStatus
from ..llm import build_chat_client, resolve_provider
from .hub import Hub, Viewer, trace_steps
from .replay import Replay

DEFAULT_MATCH = Path(__file__).resolve().parents[3] / "data" / "RGS-2026-0001.json"
DEFAULT_STATIC = Path(__file__).resolve().parents[3] / "frontend" / "dist"


def load_match(path: Path) -> MatchFile:
    return MatchFile.model_validate(json.loads(path.read_text(encoding="utf-8")))


def create_app(
    match: MatchFile | None = None, *, client=None, cache_path: Path | None = None, speed: float | None = None, autoplay: bool | None = None
) -> FastAPI:
    """App factory. Tests pass a match, a client (or None) and autoplay=False."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        m = match or load_match(Path(os.getenv("REGISTA_MATCH", DEFAULT_MATCH)))
        cp = cache_path or (Path(p) if (p := os.getenv("REGISTA_AGENT_CACHE")) else None)
        cache = WarmPath.load_cache(cp) if cp and cp.exists() else None
        llm = client if match is not None else build_chat_client()
        warm = WarmPath(m.meta, llm, cache=cache)
        hub = Hub(
            Replay(m),
            warm,
            speed=speed if speed is not None else float(os.getenv("REGISTA_SPEED", "10")),
            autoplay=autoplay if autoplay is not None else os.getenv("REGISTA_AUTOPLAY", "1") == "1",
        )
        app.state.hub = hub
        app.state.provider = "injected" if match is not None else resolve_provider()
        app.state.cache_size = len(cache or {})
        await hub.start()
        yield
        await hub.stop()

    app = FastAPI(title="Regista", version="0.2.0", lifespan=lifespan)
    origins = [o.strip() for o in os.getenv("REGISTA_CORS_ORIGINS", "*").split(",")]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])

    def hub(app_: FastAPI = app) -> Hub:
        return app_.state.hub

    @app.get("/api/health")
    async def health():
        return {"ok": True, "provider": app.state.provider, "recorded_renders": app.state.cache_size}

    @app.get("/api/match")
    async def get_match():
        return json.loads(hub().replay.match.meta.model_dump_json())

    @app.get("/api/profiles")
    async def profiles():
        return [p.model_dump() for p in PRESETS.values()]

    @app.get("/api/replay")
    async def replay_status() -> ReplayStatus:
        return hub().status()

    @app.post("/api/replay")
    async def replay_control(body: ControlRequest) -> ReplayStatus:
        try:
            return await hub().control(body.action, body.value, body.minute)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/momentum")
    async def momentum() -> list[MomentumPoint]:
        """Momentum history up to the replay clock, so a viewer joining mid-match sees the whole ribbon."""
        return [MomentumPoint(minute=m, index=i) for m, i in hub().replay.momentum]

    @app.get("/api/insights")
    async def insights():
        return [json.loads(i.model_dump_json()) for i in hub().replay.insights]

    @app.get("/api/render/{insight_id}")
    async def render(
        insight_id: str,
        profile: str | None = None,
        mode: str | None = None,
        lang: str | None = None,
        team: str | None = None,
        player: str | None = None,
    ) -> RenderResponse:
        """Render an insight for any profile on demand (the side-by-side compare view)."""
        ctx = next((c for c in hub().replay.history if c.insight.insight_id == insight_id), None)
        if ctx is None:
            raise HTTPException(404, "insight not reached yet")
        res = await hub().warm.render(ctx, profile_from_params(profile, mode, lang, team, player))
        return RenderResponse(insight=res.insight, rendered=res.rendered, trace=trace_steps(res.trace), source=res.source)

    @app.websocket("/ws")
    async def ws(
        websocket: WebSocket,
        profile: str | None = None,
        mode: str | None = None,
        lang: str | None = Query(None),
        team: str | None = None,
        player: str | None = None,
    ):
        await websocket.accept()
        viewer = Viewer(websocket.send_json, profile_from_params(profile, mode, lang, team, player))
        await hub().connect(viewer)
        try:
            while True:
                msg = await websocket.receive_json()  # viewers may also drive the replay
                if isinstance(msg, dict) and msg.pop("type", None) == "control":
                    try:
                        req = ControlRequest.model_validate(msg)
                        await hub().control(req.action, req.value, req.minute)
                    except (ValidationError, ValueError) as exc:
                        await websocket.send_json(ErrorMessage(error=str(exc)[:300]).model_dump(mode="json"))
        except WebSocketDisconnect:
            pass
        finally:
            hub().disconnect(viewer)

    static = Path(os.getenv("REGISTA_STATIC", DEFAULT_STATIC))
    if static.is_dir():  # one service in production: the API and the built overlay app
        app.mount("/", StaticFiles(directory=static, html=True), name="web")

    return app


def _env_app() -> FastAPI:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    return create_app()


app = _env_app()
