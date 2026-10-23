"""Deterministic replay of a match through the hot path.

``Replay`` owns the event cursor and the InsightPipeline. It advances by
``elapsed_s`` and returns what happened: raw events, new insights (each with
the context snapshot the warm path needs) and recaps after period summaries.
Seeking backwards rebuilds the pipeline and fast-forwards. A full match replays in
under 100 ms, and insight ids are deterministic, so render caches stay valid across seeks.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..agents.context import InsightContext, capture
from ..agents.recap import build_recap
from ..contracts.events import MatchFile, format_clock, match_minute
from ..contracts.insight import Insight
from ..detect import InsightPipeline
from ..state import Momentum

MOMENTUM_SAMPLE_MIN = 0.25


@dataclass
class Step:
    events: list = field(default_factory=list)
    moments: list[InsightContext] = field(default_factory=list)  # new insights (incl. recaps) with their state snapshots


class Replay:
    def __init__(self, match: MatchFile) -> None:
        self.match = match
        self.events = match.events
        self.end_s = self.events[-1].elapsed_s
        self.history: list[InsightContext] = []
        self.reset()

    def reset(self) -> None:
        self.pipe = InsightPipeline(self.match.meta)
        self.cursor = 0
        self.clock_s = 0.0
        self.history = []
        self.momentum: list[tuple[float, float]] = []  # (match minute, home-positive index), sampled

    @property
    def state(self):
        return self.pipe.state

    @property
    def insights(self) -> list[Insight]:
        return [c.insight for c in self.history]

    @property
    def finished(self) -> bool:
        return self.cursor >= len(self.events)

    def advance_to(self, elapsed_s: float) -> Step:
        step = Step()
        target = min(elapsed_s, self.end_s)
        while self.cursor < len(self.events) and self.events[self.cursor].elapsed_s <= target:
            ev = self.events[self.cursor]
            self.cursor += 1
            step.events.append(ev)
            self._sample_momentum(ev)
            for ins in self.pipe.process(ev):
                ctx = capture(self.pipe.state, ins)
                step.moments.append(ctx)
                if ins.kind == "period_summary":
                    recap = build_recap(self.match.meta, [c.insight for c in self.history] + [m.insight for m in step.moments], ins)
                    step.moments.append(capture(self.pipe.state, recap))
        self.history.extend(step.moments)
        self.clock_s = max(self.clock_s, target)
        return step

    def _sample_momentum(self, ev) -> None:
        minute = match_minute(ev.period, ev.t)
        if self.momentum and minute - self.momentum[-1][0] < MOMENTUM_SAMPLE_MIN:
            return
        mom = self.pipe.state.component(Momentum)
        if mom is not None:
            self.momentum.append((round(minute, 2), round(mom.index(self.pipe.state), 3)))

    def seek(self, elapsed_s: float) -> Step:
        """Jump to ``elapsed_s``; the returned step holds everything replayed on the way (for history, not for display)."""
        if elapsed_s < self.clock_s:
            self.reset()
        return self.advance_to(elapsed_s)

    def elapsed_for_minute(self, minute: float) -> float:
        """Elapsed time of the first event at or after a match minute (0-90; stoppage folds into 45 / 90)."""
        for ev in self.events:
            if match_minute(ev.period, ev.t) >= minute:
                return ev.elapsed_s
        return self.end_s

    def clock(self) -> dict:
        """Broadcast clock at the current replay time (from the last applied event)."""
        last = self.events[self.cursor - 1] if self.cursor else self.events[0]
        t = last.t + max(0.0, self.clock_s - last.elapsed_s) if last.type != "period_end" else last.t
        return {
            "period": last.period,
            "t": round(t, 2),
            "match_clock_s": round(last.match_clock_s + (t - last.t), 2),
            "elapsed_s": round(self.clock_s, 2),
            "display": format_clock(last.period, t),
        }
