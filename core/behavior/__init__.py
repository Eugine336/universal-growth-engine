"""
UGIE Core — Behavior Module

Responsibilities:
- Build and maintain behavioral profiles for every identity/entity
- Track engagement patterns (session frequency, depth, recency)
- Compute interest and intent signals from event streams
- Score entities using RFM (Recency, Frequency, Monetary)
- Detect communication preferences (channel, timing)
- Surface churn signals and re-engagement windows
- Feed enriched profiles into the prediction engine
"""

from .schema import (
    BehavioralProfile,
    EngagementProfile,
    InterestProfile,
    RFMScore,
    CommunicationPreference,
    ChurnSignal,
    IntentSignal,
)
from .builder import BehaviorBuilder
from .repository import BehaviorRepository
from .analyzer import BehaviorAnalyzer

__all__ = [
    "BehavioralProfile",
    "EngagementProfile",
    "InterestProfile",
    "RFMScore",
    "CommunicationPreference",
    "ChurnSignal",
    "IntentSignal",
    "BehaviorBuilder",
    "BehaviorRepository",
    "BehaviorAnalyzer",
]
