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
    return EvidenceRef(kind="event", ref=event_id)


def metric_ref(key: str, start_s: float | None, end_s: float | None) -> EvidenceRef:
    return EvidenceRef(kind="metric", ref=key, window_start_s=None if start_s is None else round(start_s, 2), window_end_s=end_s)


@dataclass
class FactDraft:
    key: str
    label: str
    value: float | int | str
    evidence: list[EvidenceRef]
    unit: str | None = None
    previous_value: float | int | str | None = None


@dataclass
class Draft:
    kind: str
    priority: int
    ttl_ms: int
    facts: list[FactDraft]
    hint: str
    dedupe_key: str
    scope: str = "match"  # cooldowns apply per (kind, scope), e.g. per team or per player
    team_ids: list[str] = field(default_factory=list)
    player_ids: list[str] = field(default_factory=list)


class Detector:
    kind: str = ""
    cooldown_s: float = 0.0

    def detect(self, ev, updates: list[MetricUpdate], st: MatchState) -> list[Draft]:
        raise NotImplementedError

    def admitted(self, draft: Draft) -> None:
        """Called when the pipeline accepts a draft (passed dedupe and cooldown)."""


def pct(x: float) -> int:
    return int(round(100.0 * x))
