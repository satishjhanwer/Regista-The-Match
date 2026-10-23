"""Deterministic match state engine (hot path). Never reads ground truth."""

from ..contracts.events import MatchMeta
from .control import ControlChaos
from .core import WINDOWS_S, MatchState, MetricUpdate, replay
from .models import ExpectedGoals, PassDifficulty
from .momentum import Momentum
from .press import Press
from .records import Records
from .rolling import DecayedSum, RollingSum


def default_components() -> list:
    """All analytical components, in dependency order (xG before momentum)."""
    return [PassDifficulty(), ExpectedGoals(), Momentum(), ControlChaos(), Press(), Records()]


def build_state(meta: MatchMeta) -> MatchState:
    return MatchState(meta, default_components())


__all__ = [
    "WINDOWS_S",
    "ControlChaos",
    "DecayedSum",
    "ExpectedGoals",
    "MatchState",
    "MetricUpdate",
    "Momentum",
    "PassDifficulty",
    "Press",
    "Records",
    "RollingSum",
    "build_state",
    "default_components",
    "replay",
]
