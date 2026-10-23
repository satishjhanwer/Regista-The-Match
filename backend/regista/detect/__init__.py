"""Moment detectors (hot path): MatchState -> canonical Insight with facts and evidence. Never reads ground truth."""

from .base import Detector, Draft, FactDraft
from .detectors import default_detectors
from .pipeline import InsightPipeline, run_match

__all__ = ["Detector", "Draft", "FactDraft", "InsightPipeline", "default_detectors", "run_match"]
