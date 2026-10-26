"""Streaming primitives: time-windowed sums and exponentially decayed sums.

All timestamps are ``elapsed_s`` (monotonic playing time). Every operation is
O(1) amortized: each sample is appended once and evicted once.
"""

from __future__ import annotations

import math
from collections import deque


class RollingSum:
    """Sum and count of samples with timestamp in ``(now - window_s, now]``."""

    __slots__ = ("window_s", "_q", "_sum")

    def __init__(self, window_s: float) -> None:
        self.window_s = window_s
        self._q: deque[tuple[float, float]] = deque()
        self._sum = 0.0

    def add(self, t: float, v: float = 1.0) -> None:
        """Record value ``v`` at time ``t``."""
        self._q.append((t, v))
        self._sum += v

    def _evict(self, now: float) -> None:
        q, cutoff = self._q, now - self.window_s
        while q and q[0][0] <= cutoff:
            self._sum -= q.popleft()[1]
        if not q:
            self._sum = 0.0  # drop accumulated float error whenever the window empties

    def sum(self, now: float) -> float:
        """Sum of the samples still inside the window at ``now``."""
        self._evict(now)
        return self._sum

    def count(self, now: float) -> int:
        """Number of samples still inside the window at ``now``."""
        self._evict(now)
        return len(self._q)

    def clear(self) -> None:
        """Forget every sample."""
        self._q.clear()
        self._sum = 0.0


class DecayedSum:
    """Impulse EWMA: ``sum_i w_i * 2 ** (-(now - t_i) / half_life_s)``, updated in O(1)."""

    __slots__ = ("half_life_s", "_value", "_t")

    def __init__(self, half_life_s: float) -> None:
        self.half_life_s = half_life_s
        self._value = 0.0
        self._t = 0.0

    def _decay_to(self, now: float) -> None:
        if now > self._t:
            self._value *= math.exp(-math.log(2.0) * (now - self._t) / self.half_life_s)
            self._t = now

    def add(self, now: float, w: float) -> None:
        """Decay to ``now``, then add an impulse of weight ``w``."""
        self._decay_to(now)
        self._value += w

    def value(self, now: float) -> float:
        """The decayed sum at ``now``."""
        self._decay_to(now)
        return self._value

    def reset(self, now: float) -> None:
        """Restart from zero at ``now``."""
        self._value, self._t = 0.0, now
