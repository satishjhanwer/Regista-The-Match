"""Hot-path pipeline: event -> MatchState -> detectors -> canonical Insights.

Insight ids, fact ids and ``created_at`` are derived from the match (counter,
kickoff time + elapsed_s), never from the wall clock, so the same event stream
always yields byte-identical insights.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from ..contracts.events import MatchFile, MatchMeta, format_clock
from ..contracts.insight import Entities, Fact, Insight, MatchClock
from ..state import MatchState, build_state
from .base import Detector, Draft
from .detectors import default_detectors


class InsightPipeline:
    """Hot path for one match: state, detectors, dedupe and cooldowns, and deterministic insight ids."""

    def __init__(self, meta: MatchMeta, state: MatchState | None = None, detectors: list[Detector] | None = None) -> None:
        self.meta = meta
        self.state = state or build_state(meta)
        self.detectors = detectors if detectors is not None else default_detectors()
        self.kickoff = datetime.fromisoformat(meta.kickoff_utc.replace("Z", "+00:00"))
        self.insights: list[Insight] = []
        self._seen: set[str] = set()
        self._last_fired: dict[tuple[str, str], float] = {}
        self._count = 0

    def process(self, ev) -> list[Insight]:
        """Apply one event and return the insights it produced."""
        updates = self.state.apply(ev)
        new: list[Insight] = []
        for det in self.detectors:
            for draft in det.detect(ev, updates, self.state):
                if self._admit(det, draft):
                    det.admitted(draft)
                    new.append(self._build(ev, draft))
        self.insights.extend(new)
        return new

    def _admit(self, det: Detector, draft: Draft) -> bool:
        if draft.dedupe_key in self._seen:
            return False
        scope = (draft.kind, draft.scope)
        last = self._last_fired.get(scope)
        if last is not None and self.state.now - last < det.cooldown_s:
            return False
        self._seen.add(draft.dedupe_key)
        self._last_fired[scope] = self.state.now
        return True

    def _build(self, ev, d: Draft) -> Insight:
        self._count += 1
        insight_id = f"{self.meta.match_id}-INS-{self._count:04d}"
        facts = [
            Fact(
                fact_id=f"{insight_id}-F{i + 1}",
                key=f.key,
                label=f.label,
                value=f.value,
                unit=f.unit,
                previous_value=f.previous_value,
                evidence=f.evidence,
            )
            for i, f in enumerate(d.facts)
        ]
        return Insight(
            insight_id=insight_id,
            match_id=self.meta.match_id,
            kind=d.kind,
            priority=d.priority,
            clock=MatchClock(period=ev.period, t=ev.t, match_clock_s=ev.match_clock_s, display=format_clock(ev.period, ev.t)),
            created_at=self.kickoff + timedelta(seconds=ev.elapsed_s),
            ttl_ms=d.ttl_ms,
            entities=Entities(team_ids=d.team_ids, player_ids=d.player_ids),
            facts=facts,
            why_it_matters_hint=d.hint,
        )


def run_match(match: MatchFile) -> tuple[list[Insight], list[float]]:
    """Replay a whole match. Returns the insights and the per-event processing time in seconds."""
    pipe = InsightPipeline(match.meta)
    timings: list[float] = []
    clock = time.perf_counter
    for ev in match.events:
        t0 = clock()
        pipe.process(ev)
        timings.append(clock() - t0)
    return pipe.insights, timings
