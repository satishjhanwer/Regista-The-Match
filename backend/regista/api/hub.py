"""Broadcast hub: one shared replay clock, many viewers, one rendering per profile.

Every tick advances the replay by ``tick_s * speed`` seconds of match time and
pushes to each socket (messages are ``regista.contracts.stream`` models):

* ``tick``: clock, score, play state and live metrics (momentum, chaos, control, press)
* ``events``: the raw events in that tick, compacted for the pitch view
* ``overlay``: an OverlayPayload when an insight is relevant to that viewer's profile,
  as soon as the warm path has rendered it (Analyst -> Narrator -> Verifier, or cache)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import asdict

from ..agents.context import InsightContext
from ..agents.orchestrator import WarmPath
from ..agents.profiles import display_for
from ..contracts.events import Model
from ..contracts.insight import FanProfile, OverlayPayload
from ..contracts.stream import (
    EventsMessage,
    HelloMessage,
    LiveMetrics,
    OverlayMessage,
    ReplayStatus,
    ResetMessage,
    StreamClock,
    StreamEvent,
    TickMessage,
    TraceStep,
)
from ..state import ControlChaos, Momentum, Press
from .replay import Replay

log = logging.getLogger("regista.hub")

SPEED_MIN, SPEED_MAX = 0.25, 120.0
_EVENT_EXTRAS = ("end_x", "end_y", "outcome", "height", "is_cross", "is_through_ball", "top_speed_kmh", "shot_speed_kmh", "cause")


def compact_event(ev) -> StreamEvent:
    extras = {k: v for k in _EVENT_EXTRAS if (v := getattr(ev, k, None)) is not None}
    return StreamEvent(
        id=ev.event_id, type=ev.type, period=ev.period, t=ev.t, team=ev.team_id, player=ev.player_id, x=ev.x, y=ev.y, **extras
    )


def trace_steps(steps) -> list[TraceStep]:
    return [TraceStep.model_validate(asdict(s)) for s in steps]


class Viewer:
    def __init__(self, send, profile: FanProfile) -> None:
        self.send = send  # async callable taking a JSON-ready dict
        self.profile = profile


class Hub:
    def __init__(self, replay: Replay, warm: WarmPath, *, speed: float = 10.0, tick_s: float = 0.1, autoplay: bool = True) -> None:
        self.replay = replay
        self.warm = warm
        self.speed = speed
        self.tick_s = tick_s
        self.playing = autoplay
        self.viewers: set[Viewer] = set()
        self._task: asyncio.Task | None = None
        self._renders: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ #
    async def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        for t in list(self._renders):
            t.cancel()

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.tick_s)
            if self.playing:
                await self.step(self.tick_s * self.speed)
                if self.replay.finished:
                    self.playing = False
                    await self.broadcast(self.tick_message())

    async def step(self, match_seconds: float) -> None:
        step = self.replay.advance_to(self.replay.clock_s + match_seconds)
        if step.events:
            await self.broadcast(EventsMessage(events=[compact_event(e) for e in step.events]))
        await self.broadcast(self.tick_message())
        for ctx in step.moments:
            for viewer in list(self.viewers):
                self._dispatch(ctx, viewer)

    async def wait_renders(self) -> None:
        """Wait for in-flight renders (tests and the recorder use this)."""
        while self._renders:
            await asyncio.gather(*list(self._renders), return_exceptions=True)

    # ------------------------------------------------------------------ #
    def _dispatch(self, ctx: InsightContext, viewer: Viewer) -> None:
        if display_for(ctx.insight, viewer.profile) is None:
            return
        task = asyncio.create_task(self._render_and_send(ctx, viewer))
        self._renders.add(task)
        task.add_done_callback(self._renders.discard)

    async def _render_and_send(self, ctx: InsightContext, viewer: Viewer) -> None:
        try:
            res = await self.warm.render(ctx, viewer.profile)
        except Exception:
            log.exception("render failed for %s", ctx.insight.insight_id)
            return
        display = display_for(res.insight, viewer.profile)
        if display is None or res.rendered.verification.status not in ("verified", "revised"):
            return  # nothing unverified ever reaches the screen
        payload = OverlayPayload(insight=res.insight, rendered=res.rendered, display=display)
        msg = OverlayMessage(source=res.source, payload=payload, trace=trace_steps(res.trace))
        if viewer in self.viewers:
            await self._safe_send(viewer, msg)

    async def _safe_send(self, viewer: Viewer, msg: Model) -> None:
        try:
            await viewer.send(msg.model_dump(mode="json"))
        except Exception:
            self.viewers.discard(viewer)

    async def broadcast(self, msg: Model) -> None:
        data = msg.model_dump(mode="json")  # serialize once for every viewer
        for viewer in list(self.viewers):
            try:
                await viewer.send(data)
            except Exception:
                self.viewers.discard(viewer)

    # ------------------------------------------------------------------ #
    async def connect(self, viewer: Viewer) -> None:
        self.viewers.add(viewer)
        hello = HelloMessage(match=self.replay.match.meta, profile=viewer.profile, replay=self.status())
        await viewer.send(hello.model_dump(mode="json"))
        await viewer.send(self.tick_message().model_dump(mode="json"))

    def disconnect(self, viewer: Viewer) -> None:
        self.viewers.discard(viewer)

    async def control(self, action: str, value: float | None = None, minute: float | None = None) -> ReplayStatus:
        if action == "play":
            if self.replay.finished:
                await self._seek(0.0)
            self.playing = True
        elif action == "pause":
            self.playing = False
        elif action == "speed":
            if value is None:
                raise ValueError("speed needs a value")
            self.speed = max(SPEED_MIN, min(SPEED_MAX, float(value)))
        elif action == "seek":
            target = self.replay.elapsed_for_minute(minute) if minute is not None else float(value or 0.0)
            await self._seek(target)
        elif action == "step":
            await self.step(float(value or 1.0))
        elif action == "restart":
            await self._seek(0.0)
        else:
            raise ValueError(f"unknown action {action!r}")
        await self.broadcast(self.tick_message())
        return self.status()

    async def _seek(self, elapsed_s: float) -> None:
        backwards = elapsed_s < self.replay.clock_s
        self.replay.seek(elapsed_s)  # skipped moments go to history, not to screens
        if backwards:
            await self.broadcast(ResetMessage())

    def status(self) -> ReplayStatus:
        return ReplayStatus(
            playing=self.playing,
            speed=self.speed,
            finished=self.replay.finished,
            clock=StreamClock(**self.replay.clock()),
            viewers=len(self.viewers),
        )

    def tick_message(self) -> TickMessage:
        st = self.replay.state
        mom, cc, press = st.component(Momentum), st.component(ControlChaos), st.component(Press)
        metrics = LiveMetrics(
            momentum_index=round(mom.index(st), 3) if mom else 0.0,
            momentum={t: round(mom.share(t, st), 3) for t in st.team_ids} if mom else {},
            chaos=round(cc.chaos, 3) if cc and cc.chaos is not None else None,
            control={t: round(v, 3) for t, v in cc.control.items() if v is not None} if cc else {},
            xg={t: round(st.totals[t]["xg"], 2) for t in st.team_ids},
            pressed_share={t: round(st.ratio(st.opp(t), "pressed_passes", "passes") or 0.0, 3) for t in st.team_ids},
            press_cusum={t: round(c.s, 2) for t, c in press.cusum.items()} if press else {},
        )
        return TickMessage(
            clock=StreamClock(**self.replay.clock()), score=dict(st.score), playing=self.playing, speed=self.speed, metrics=metrics
        )
