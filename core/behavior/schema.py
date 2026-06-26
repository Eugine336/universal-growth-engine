"""
Behavioral Profile Schema

The behavioral profile is the engine's living model of a user.

It is not what the user told us.
It is what the user's actions reveal about them.

Every event updates the profile.
The profile feeds every prediction.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class EngagementProfile(BaseModel):
    """
    Tracks how actively and deeply a user engages with the platform.
    """
    # Session metrics
    total_sessions: int = 0
    sessions_last_7d: int = 0
    sessions_last_30d: int = 0
    avg_session_duration_seconds: float = 0.0
    last_session_at: Optional[datetime] = None

    # Page / feature depth
    total_events: int = 0
    total_page_views: int = 0
    total_feature_uses: int = 0
    unique_features_used: List[str] = Field(default_factory=list)

    # Recency
    first_seen_at: Optional[datetime] = None
    last_active_at: Optional[datetime] = None
    days_since_last_active: Optional[float] = None

    # Streaks
    current_streak_days: int = 0
    longest_streak_days: int = 0

    # Computed engagement tier
    # cold | warming | active | power
    tier: str = "cold"


class InterestProfile(BaseModel):
    """
    Tracks what the user cares about — inferred from behavior.
    """
    # Category interests: category → interaction count
    category_interests: Dict[str, int] = Field(default_factory=dict)

    # Search terms observed
    search_terms: List[str] = Field(default_factory=list)

    # Items viewed, saved, shared
    viewed_item_ids: List[str] = Field(default_factory=list)
    saved_item_ids: List[str] = Field(default_factory=list)
    shared_item_ids: List[str] = Field(default_factory=list)

    # Top interests (computed from category_interests)
    top_interests: List[str] = Field(default_factory=list)

    # Content consumption
    total_content_viewed: int = 0
    total_content_liked: int = 0


class RFMScore(BaseModel):
    """
    Recency, Frequency, Monetary scoring.

    Standard RFM model adapted for any domain:
    - Recency: how recently did they last transact/convert?
    - Frequency: how often do they transact/convert?
    - Monetary: what is the total value they've generated?

    Each dimension scored 1–5. Combined score = R + F + M (max 15).
    """
    recency_score: int = 0          # 1 (oldest) → 5 (most recent)
    frequency_score: int = 0        # 1 (rarest) → 5 (most frequent)
    monetary_score: int = 0         # 1 (lowest value) → 5 (highest value)
    combined_score: int = 0         # sum of above

    # Raw values
    days_since_last_conversion: Optional[float] = None
    total_conversions: int = 0
    total_monetary_value: float = 0.0
    avg_monetary_value: float = 0.0

    # Segment derived from RFM
    # champions | loyal | at_risk | hibernating | lost | new | promising
    segment: str = "new"

    computed_at: Optional[datetime] = None


class CommunicationPreference(BaseModel):
    """
    Observed communication preferences — inferred from behavior.
    Not what the user said they prefer. What their actions show.
    """
    # Channel response rates: channel → open/click rate
    email_open_rate: float = 0.0
    email_click_rate: float = 0.0
    push_open_rate: float = 0.0
    sms_response_rate: float = 0.0

    # Total sends per channel
    email_sends: int = 0
    push_sends: int = 0
    sms_sends: int = 0

    # Best performing channel
    preferred_channel: Optional[str] = None

    # Time-of-day engagement (hour → engagement count)
    hourly_engagement: Dict[int, int] = Field(default_factory=dict)
    best_hour: Optional[int] = None

    # Day-of-week engagement
    daily_engagement: Dict[str, int] = Field(default_factory=dict)
    best_day: Optional[str] = None

    # Unsubscribed channels
    unsubscribed_channels: List[str] = Field(default_factory=list)


class IntentSignal(BaseModel):
    """A single detected intent signal from user behavior."""
    signal_type: str           # e.g. "purchase_intent", "churn_risk", "upsell_ready"
    strength: float            # 0.0 → 1.0
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    triggering_events: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ChurnSignal(BaseModel):
    """
    Churn risk assessment based on behavioral decay signals.
    """
    risk_level: str = "low"    # low | medium | high | critical
    risk_score: float = 0.0    # 0.0 → 1.0

    # Contributing factors
    days_inactive: float = 0.0
    engagement_decay_rate: float = 0.0     # % drop in sessions vs prior period
    session_frequency_drop: float = 0.0
    has_friction_events: bool = False
    recent_friction_count: int = 0
    cancelled_subscription: bool = False

    assessed_at: Optional[datetime] = None


class BehavioralProfile(BaseModel):
    """
    The complete behavioral profile for one identity.

    Built incrementally from every event the identity produces.
    The engine's primary input for all predictions and decisions.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    identity_id: str
    application_id: str

    # Sub-profiles
    engagement: EngagementProfile = Field(default_factory=EngagementProfile)
    interests: InterestProfile = Field(default_factory=InterestProfile)
    rfm: RFMScore = Field(default_factory=RFMScore)
    communication: CommunicationPreference = Field(default_factory=CommunicationPreference)
    churn: ChurnSignal = Field(default_factory=ChurnSignal)

    # Intent signals (rolling window — most recent per type)
    intent_signals: Dict[str, IntentSignal] = Field(default_factory=dict)

    # Raw event counts by type (for fast lookups)
    event_counts: Dict[str, int] = Field(default_factory=dict)

    # Computed traits (high-level labels)
    traits: Dict[str, Any] = Field(default_factory=dict)

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_event_at: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def increment_event(self, event_type: str) -> None:
        self.event_counts[event_type] = self.event_counts.get(event_type, 0) + 1

    def get_event_count(self, event_type: str) -> int:
        return self.event_counts.get(event_type, 0)

    def set_intent_signal(self, signal: IntentSignal) -> None:
        self.intent_signals[signal.signal_type] = signal

    def get_intent_signal(self, signal_type: str) -> Optional[IntentSignal]:
        return self.intent_signals.get(signal_type)

    def set_trait(self, key: str, value: Any) -> None:
        self.traits[key] = value

    def touch(self, event_time: Optional[datetime] = None) -> None:
        now = event_time or datetime.now(timezone.utc)
        self.updated_at = now
        self.last_event_at = now
