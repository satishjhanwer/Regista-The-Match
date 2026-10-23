"""Wire contract for the replay API: WebSocket messages, render responses, control requests.

The hub builds every message from these models, and the frontend's types are
generated from their schema, so the two cannot drift.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field

from .events import MatchMeta, Model
from .insight import FanProfile, Insight, OverlayPayload, RenderedInsight


class StreamClock(Model):
    period: Literal[1, 2]
    t: float
    match_clock_s: float
    elapsed_s: float
    display: str


class LiveMetrics(Model):
    momentum_index: float = Field(description="Home-positive momentum index in [-1, 1]")
    momentum: dict[str, float] = Field(description="Team id -> share of momentum, 0..1")
    chaos: float | None = Field(description="Match chaos index over 5 min, 0 calm .. 1 chaotic")
    control: dict[str, float] = Field(description="Team id -> control score over 5 min, 0..1")
    xg: dict[str, float]
    pressed_share: dict[str, float] = Field(description="Pressing team id -> share of opponent passes under pressure (5 min)")
    press_cusum: dict[str, float]


class ReplayStatus(Model):
    playing: bool
    speed: float = Field(description="Match seconds per wall-clock second")
    finished: bool
    clock: StreamClock
    viewers: int


class TraceStep(Model):
    agent: Literal["analyst", "narrator", "verifier", "template", "cache"]
    action: str
    status: Literal["ok", "rejected", "error", "fallback"]
    ms: float
    detail: dict[str, Any] = {}


RenderSource = Literal["llm", "llm_revised", "template", "template_fallback", "cache"]


class MomentumPoint(Model):
    minute: float = Field(description="Football minute (stoppage folded into 45 / 90)")
    index: float = Field(description="Home-positive momentum index in [-1, 1]")


class StreamEvent(Model):
    """A match event compacted for the pitch view (absolute pitch metres)."""

    id: str
    type: str
    period: Literal[1, 2]
    t: float
    team: str | None
    player: str | None
    x: float
    y: float
    end_x: float | None = None
    end_y: float | None = None
    outcome: str | None = None
    height: str | None = None
    is_cross: bool = False
    is_through_ball: bool = False
    top_speed_kmh: float | None = None
    shot_speed_kmh: float | None = None
    cause: str | None = None


class HelloMessage(Model):
    type: Literal["hello"] = "hello"
    match: MatchMeta
    profile: FanProfile
    replay: ReplayStatus


class TickMessage(Model):
    type: Literal["tick"] = "tick"
    clock: StreamClock
    score: dict[str, int]
    playing: bool
    speed: float
    metrics: LiveMetrics


class EventsMessage(Model):
    type: Literal["events"] = "events"
    events: list[StreamEvent]


class OverlayMessage(Model):
    type: Literal["overlay"] = "overlay"
    source: RenderSource
    payload: OverlayPayload
    trace: list[TraceStep]


class ResetMessage(Model):
    type: Literal["reset"] = "reset"


class ErrorMessage(Model):
    type: Literal["error"] = "error"
    error: str


StreamMessage = Annotated[
    HelloMessage | TickMessage | EventsMessage | OverlayMessage | ResetMessage | ErrorMessage,
    Field(discriminator="type"),
]


class RenderResponse(Model):
    """GET /api/render/{insight_id}."""

    insight: Insight
    rendered: RenderedInsight
    trace: list[TraceStep]
    source: RenderSource


class ControlRequest(Model):
    """POST /api/replay, or {"type": "control", ...} on the socket."""

    action: Literal["play", "pause", "speed", "seek", "step", "restart"]
    value: float | None = None
    minute: float | None = None


class StreamContract(Model):
    """Schema root that bundles the wire types for code generation. Never sent itself."""

    message: StreamMessage
    render: RenderResponse
    control: ControlRequest
    status: ReplayStatus
    momentum: list[MomentumPoint]
