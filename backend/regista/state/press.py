"""Press intensity and press change-point detection.

Metrics, per pressing team P against opponent O, over the rolling windows:

* ``P.pressures_per_opp_pass_{5m,10m}``: P's pressure events per O pass (PPDA-like, inverted so
  higher = more pressing).
* ``P.pressed_pass_share_5m``: share of O's passes played with a P defender within 5 m.

Change-point: a one-sided CUSUM per half on O's passes, with observation
``y = 1`` if the passer had a P defender within 5 m. Pressure events are bursty
(several per possession), which made a CUSUM on raw pressure counts far noisier
for the same detection delay. The pressed-pass indicator is one Bernoulli draw
per pass. See docs/DECISIONS.md.

* Baseline ``mu0``: mean of ``y`` over the first 20 minutes of the half, using in-control samples only
  (CUSUM below ``H / 2`` and not gated). The CUSUM arms after 5 minutes of the half.
* ``S = max(0, S + y - (mu0 + K))``. ``K`` is set from the smallest shift worth calling a press
  change (``mu0 + 0.5`` pressed share), not from noise alone.
* Alarm when ``S > H`` and the pressed share over the last 3 minutes is at least ``mu0 + 0.25``
  (confirmation); otherwise S is held (capped at 2H) until it confirms or decays. Reset after an alarm.
  The run start (last time S was 0) is the change-point estimate and the evidence window start.
* Stability gate: a press change means P presses harder while keeping its own game. When P's own
  completion collapses (last 3 min below its baseline by 0.12, or its last 5 passes below by 0.25)
  the whole match is in a chaos spell; that is reported by control vs chaos, so the CUSUM resets.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .core import MatchState, MetricUpdate
from .rolling import RollingSum

K = 0.25
H = 2.5
BASELINE_S = 1200.0
ARM_S = 300.0
GATE_WINDOW_S = 180.0
GATE_MIN_PASSES = 4
GATE_DROP = 0.12
GATE_LAST_N = 5
GATE_LAST_DROP = 0.25
CONFIRM_WINDOW_S = 180.0
CONFIRM_DELTA = 0.25
DEFAULT_COMPLETION = 0.8


@dataclass(frozen=True)
class PressAlarm:
    team_id: str
    period: int
    t: float
    elapsed_s: float
    change_start_s: float
    baseline_pressed_share: float
    recent_pressed_share: float
    baseline_pressures_per_pass: float
    pressures_per_pass_5m: float
    pressure_event_ids: tuple[str, ...]


class _Cusum:
    """Per-team, per-half CUSUM state."""

    def __init__(self, start_s: float) -> None:
        self.start_s = start_s
        self.s = 0.0
        self.run_start_s = start_s
        self.base_y = self.base_n = 0.0
        self.base_pressures = self.base_opp_passes = 0.0
        self.own_base_n = self.own_base_c = 0.0
        self.own_recent: deque[tuple[float, bool]] = deque()
        self.own_last: deque[bool] = deque(maxlen=GATE_LAST_N)
        self.recent_y = RollingSum(CONFIRM_WINDOW_S)
        self.gated = False

    def in_baseline(self, now: float) -> bool:
        return now - self.start_s <= BASELINE_S

    @property
    def mu0(self) -> float:
        return self.base_y / self.base_n if self.base_n else 0.0

    def gate(self, now: float) -> bool:
        q = self.own_recent
        while q and q[0][0] <= now - GATE_WINDOW_S:
            q.popleft()
        c0 = self.own_base_c / self.own_base_n if self.own_base_n >= 10 else DEFAULT_COMPLETION
        if len(q) >= GATE_MIN_PASSES and sum(ok for _, ok in q) / len(q) < c0 - GATE_DROP:
            return True
        last = self.own_last
        return len(last) == GATE_LAST_N and sum(last) / GATE_LAST_N < c0 - GATE_LAST_DROP


class Press:
    def __init__(self) -> None:
        self.cusum: dict[str, _Cusum] = {}
        self.alarms: list[PressAlarm] = []
        self.recent_pressures: dict[str, deque[tuple[float, str]]] = {}

    def apply(self, ev, st: MatchState, out: list[MetricUpdate]) -> None:
        if ev.type == "period_start" or not self.cusum:
            self.cusum = {t: _Cusum(st.now) for t in st.team_ids}
            self.recent_pressures = {t: deque(maxlen=32) for t in st.team_ids}
        if ev.type == "pressure":
            self.recent_pressures[ev.team_id].append((st.now, ev.event_id))
            self._emit_ratios(ev.team_id, st, out)
            c = self.cusum[ev.team_id]
            if c.in_baseline(st.now) and not c.gated and c.s < H / 2:
                c.base_pressures += 1
        elif ev.type == "pass":
            own = self.cusum[ev.team_id]
            ok = ev.outcome == "complete"
            own.own_recent.append((st.now, ok))
            own.own_last.append(ok)
            if own.in_baseline(st.now):
                own.own_base_n += 1
                own.own_base_c += ok
            presser = st.opp(ev.team_id)
            self._emit_ratios(presser, st, out)
            self._step(presser, ev, st, out)

    def _emit_ratios(self, p: str, st: MatchState, out: list[MetricUpdate]) -> None:
        o = st.opp(p)
        for label in ("5m", "10m"):
            n = st.window(o, "passes", label)
            if n:
                st.emit(out, f"{p}.pressures_per_opp_pass_{label}", st.window(p, "pressures", label) / n, label)
        n = st.window(o, "passes")
        if n:
            st.emit(out, f"{p}.pressed_pass_share_5m", st.window(o, "pressed_passes") / n, "5m")

    def _step(self, p: str, ev, st: MatchState, out: list[MetricUpdate]) -> None:
        c = self.cusum[p]
        y = 1.0 if ev.pressure.defenders_within_5m >= 1 else 0.0
        now = st.now
        c.recent_y.add(now, y)
        gated = c.gate(now)
        if c.in_baseline(now) and not gated and c.s < H / 2:
            c.base_y += y
            c.base_n += 1
            c.base_opp_passes += 1
        if now - c.start_s < ARM_S:
            return
        if gated:
            c.s, c.gated = 0.0, True
            st.emit(out, f"{p}.press_cusum", 0.0)
            return
        c.gated = False
        if c.s == 0.0:
            c.run_start_s = now
        c.s = max(0.0, c.s + y - (c.mu0 + K))
        st.emit(out, f"{p}.press_cusum", c.s)
        if c.s > H:
            n = c.recent_y.count(now)
            if n and c.recent_y.sum(now) / n >= c.mu0 + CONFIRM_DELTA:
                self._alarm(p, ev, st, out)
                c.s = 0.0
            else:
                c.s = min(c.s, 2 * H)  # hold until the recent pressed share confirms the shift

    def _alarm(self, p: str, ev, st: MatchState, out: list[MetricUpdate]) -> None:
        c, o = self.cusum[p], st.opp(p)
        n5 = st.window(o, "passes")
        ids = tuple(eid for t, eid in self.recent_pressures[p] if t >= c.run_start_s)[-6:]
        alarm = PressAlarm(
            team_id=p,
            period=ev.period,
            t=ev.t,
            elapsed_s=st.now,
            change_start_s=c.run_start_s,
            baseline_pressed_share=c.mu0,
            recent_pressed_share=st.window(o, "pressed_passes") / n5 if n5 else 0.0,
            baseline_pressures_per_pass=c.base_pressures / c.base_opp_passes if c.base_opp_passes else 0.0,
            pressures_per_pass_5m=st.window(p, "pressures") / n5 if n5 else 0.0,
            pressure_event_ids=ids,
        )
        self.alarms.append(alarm)
        out.append(MetricUpdate(f"{p}.press_alarm", 1.0, st.now, c.run_start_s, st.now))

    def snapshot(self, st: MatchState) -> dict:
        return {"press_cusum": {t: round(c.s, 3) for t, c in self.cusum.items()}}
