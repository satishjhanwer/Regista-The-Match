"""Insight and overlay contract.

One canonical ``Insight`` per detected moment carries the facts and the
evidence behind them. Personalization never changes facts: it produces one
``RenderedInsight`` per audience profile, and every claim in a rendering
cites the fact ids it relies on so the Verifier can check it mechanically.
``OverlayPayload`` is what goes over the wire to the renderer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .events import Model

InsightKind = Literal[
    "goal",
    "momentum_shift",
    "press_change",
    "control_vs_chaos",
    "rhythm_shift",
    "shot_quality",
    "key_pass",
    "player_tag",
    "milestone",
    "period_summary",
    "recap",
]


class MatchClock(Model):
    """When a moment happened, with its broadcast display string."""

    period: Literal[1, 2]
    t: float = Field(ge=0)
    match_clock_s: float = Field(ge=0)
    display: str


class EvidenceRef(Model):
    """What a fact rests on: an event id, or a metric key with its time window (elapsed seconds)."""

    kind: Literal["event", "metric"]
    ref: str = Field(description="event_id for events, metric key (e.g. 'away.ppda') for metrics")
    window_start_s: float | None = None
    window_end_s: float | None = None


class Fact(Model):
    """One number or value with its label, optional baseline and evidence. The unit of truth."""

    fact_id: str
    key: str = Field(description="Stable machine key, e.g. 'home.pass_completion_own_half'")
    label: str = Field(description="Human label in English; renderers localize")
    value: float | int | str
    unit: str | None = None
    previous_value: float | int | str | None = Field(default=None, description="Baseline the value is compared against, for deltas")
    evidence: list[EvidenceRef]


class Entities(Model):
    """Teams and players an insight is about."""

    team_ids: list[str] = []
    player_ids: list[str] = []


class Verification(Model):
    """The Verifier's verdict on a rendering."""

    status: Literal["pending", "verified", "revised", "rejected"]
    checked_claims: int = 0
    rejected_claims: int = 0
    notes: list[str] = []


class Insight(Model):
    """A detected moment: one canonical set of facts that every rendering must stay within."""

    insight_id: str
    match_id: str
    kind: InsightKind
    priority: int = Field(ge=1, le=5, description="5 = interrupt-worthy")
    clock: MatchClock
    created_at: datetime
    ttl_ms: int = Field(gt=0)
    entities: Entities
    facts: list[Fact]
    why_it_matters_hint: str = Field(description="Deterministic detector rationale handed to the agents, never shown verbatim")


ViewingMode = Literal["analyst", "casual", "player_focus"]


class FanProfile(Model):
    """Who is watching: viewing mode, language, favourite club, focus player, metric of interest."""

    profile_id: str
    mode: ViewingMode
    language: str = Field(description="BCP 47 tag, e.g. en, hi, es")
    favorite_team_id: str | None = None
    focus_player_id: str | None = None
    metric_of_interest: str | None = None


class Claim(Model):
    """One sentence and the facts it relies on."""

    text: str
    fact_ids: list[str] = Field(description="Facts this sentence relies on; empty means opinion/colour only")


class StatCallout(Model):
    """The one stat a graphic highlights."""

    label: str
    value: str
    fact_id: str


class RenderedInsight(Model):
    """An insight told for one fan profile."""

    insight_id: str
    profile_id: str
    language: str
    mode: ViewingMode
    headline: str = Field(max_length=80)
    body: str = Field(max_length=320)
    stat_callout: StatCallout | None = None
    claims: list[Claim]
    verification: Verification


OverlaySlot = Literal["lower_third", "top_bar", "side_panel", "ticker", "player_tag"]


class DisplayDirective(Model):
    """Where and when a graphic airs, and for how long."""

    slot: OverlaySlot
    template_id: str
    show_at_match_clock_s: float = Field(ge=0)
    ttl_ms: int = Field(gt=0)
    priority: int = Field(ge=1, le=5)


class OverlayPayload(Model):
    """What goes over the wire to the overlay: the insight, its rendering and where to show it."""

    schema_version: str = "1.0"
    insight: Insight
    rendered: RenderedInsight
    display: DisplayDirective
