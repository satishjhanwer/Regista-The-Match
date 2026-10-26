"""Detector protocol and the drafts detectors return.

A detector looks at the event just applied, the metric updates it produced
and the state, and returns zero or more ``Draft`` insights. The pipeline owns
ids, dedupe and cooldowns, so detectors stay small and stateless where they can.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..contracts.insight import EvidenceRef
from ..state import MatchState, MetricUpdate


def event_ref(event_id: str) -> EvidenceRef:
    """Evidence pointing at one event."""
    return EvidenceRef(kind="event", ref=event_id)


def metric_ref(key: str, start_s: float | None, end_s: float | None) -> EvidenceRef:
    """Evidence pointing at a metric over a window (elapsed seconds; None for match-level facts)."""
    return EvidenceRef(kind="metric", ref=key, window_start_s=None if start_s is None else round(start_s, 2), window_end_s=end_s)


@dataclass
class FactDraft:
    """A fact before the pipeline assigns its id."""

    key: str
    label: str
    value: float | int | str
    evidence: list[EvidenceRef]
    unit: str | None = None
    previous_value: float | int | str | None = None


@dataclass
class Draft:
    """An insight before the pipeline assigns ids.

    ``dedupe_key`` identifies the moment; cooldowns apply per (kind, ``scope``), where scope is a team, a player or
    ``match``.
    """

    kind: str
    priority: int
    ttl_ms: int
    facts: list[FactDraft]
    hint: str
    dedupe_key: str
    scope: str = "match"
    team_ids: list[str] = field(default_factory=list)
    player_ids: list[str] = field(default_factory=list)


class Detector:
    """Base class: ``detect`` turns the current event and state into drafts."""

    kind: str = ""
    cooldown_s: float = 0.0

    def detect(self, ev, updates: list[MetricUpdate], st: MatchState) -> list[Draft]:
        """Drafts for this event; ``updates`` are the metrics the event changed."""
        raise NotImplementedError

    def admitted(self, draft: Draft) -> None:
        """Called when the pipeline accepts a draft (passed dedupe and cooldown)."""


def pct(x: float) -> int:
    """A 0-1 share as an integer percentage."""
    return int(round(100.0 * x))
