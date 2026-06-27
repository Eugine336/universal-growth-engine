"""
UGIE Core — Experimentation Engine

A/B testing at decision time. Assigns identities to experiment variants
using deterministic hash bucketing and applies variant overrides to decisions.
"""

from .schema import (
    Experiment,
    ExperimentAssignment,
    ExperimentStatus,
    ExperimentVariant,
)
from .engine import ExperimentationEngine

__all__ = [
    "Experiment",
    "ExperimentAssignment",
    "ExperimentStatus",
    "ExperimentVariant",
    "ExperimentationEngine",
]
