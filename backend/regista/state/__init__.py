"""Deterministic match state engine (hot path). Never reads ground truth."""

from .core import WINDOWS_S, MatchState, MetricUpdate, replay
from .rolling import DecayedSum, RollingSum

__all__ = ["WINDOWS_S", "DecayedSum", "MatchState", "MetricUpdate", "RollingSum", "replay"]
