"""
Behavior Builder

The behavior builder is called on every processed event.

It takes the event + the current behavioral profile and updates
the profile with new signals extracted from the event.

Each update method handles one aspect of the profile:
- engagement: sessions, depth, recency
- interests: categories, items, searches
- rfm: conversions and monetary value
- communication: channel responses
- churn: decay signals
- intent: high-signal behavioral patterns
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from core.events.schema import Event, EventType
from .schema import (
    BehavioralProfile,
    IntentSignal,
    ChurnSignal,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Events that indicate a monetary conversion
MONETARY_EVENTS = {
    EventType.PAYMENT_COMPLETED,
    EventType.ORDER_COMPLETED,
    EventType.SUBSCRIPTION_STARTED,
    EventType.SUBSCRIPTION_RENEWED,
}

# Events that reset churn clock
REACTIVATION_EVENTS = {
    EventType.SESSION_STARTED,
    EventType.PAYMENT_COMPLETED,
    EventType.ORDER_CREATED,
    EventType.FEATURE_USED,
    EventType.SUBSCRIPTION_RENEWED,
}

# Events that indicate friction / churn risk
FRICTION_EVENTS = {
    EventType.PAYMENT_FAILED,
    EventType.ORDER_CANCELLED,
    EventType.DISPUTE_OPENED,
    EventType.EMAIL_UNSUBSCRIBED,
    EventType.SUBSCRIPTION_CANCELLED,
    EventType.LOGIN_FAILED,
    EventType.REFUND_INITIATED,
}

# Events that signal purchase intent
PURCHASE_INTENT_EVENTS = {
    EventType.ITEM_VIEWED,
    EventType.ITEM_SAVED,
    EventType.SEARCH_EXECUTED,
    EventType.OFFER_MADE,
    EventType.ORDER_CREATED,
}

# Email engagement events
EMAIL_OPEN_EVENTS = {EventType.EMAIL_OPENED}
EMAIL_CLICK_EVENTS = {EventType.EMAIL_CLICKED}
EMAIL_NEGATIVE_EVENTS = {EventType.EMAIL_UNSUBSCRIBED, EventType.EMAIL_BOUNCED}


class BehaviorBuilder:
    """
    Incrementally updates a BehavioralProfile from a single Event.

    Usage:
        builder = BehaviorBuilder()
        profile = BehaviorRepository().get_or_create(identity_id, application_id)
        builder.apply(event, profile)
        repository.save(profile)
    """

    def apply(self, event: Event, profile: BehavioralProfile) -> BehavioralProfile:
        """Apply an event to the behavioral profile. Returns the updated profile."""
        profile.increment_event(event.type.value)
        profile.touch(event.timestamp)

        self._update_engagement(event, profile)
        self._update_interests(event, profile)
        self._update_rfm(event, profile)
        self._update_communication(event, profile)
        self._update_churn_signals(event, profile)
        self._update_intent_signals(event, profile)

        logger.debug(
            f"Behavior updated | identity={profile.identity_id} "
            f"event={event.type.value} app={profile.application_id}"
        )
        return profile

    # ------------------------------------------------------------------
    # Engagement
    # ------------------------------------------------------------------

    def _update_engagement(self, event: Event, profile: BehavioralProfile) -> None:
        eng = profile.engagement
        eng.total_events += 1

        now = event.timestamp
        if not eng.first_seen_at:
            eng.first_seen_at = now
        eng.last_active_at = now

        # Recency
        eng.days_since_last_active = 0.0

        # Session tracking
        if event.type == EventType.SESSION_STARTED:
            eng.total_sessions += 1
            eng.last_session_at = now
            self._update_session_window_counts(eng, now)

        # Page views
        if event.type == EventType.PAGE_VIEWED:
            eng.total_page_views += 1

        # Feature usage
        if event.type == EventType.FEATURE_USED:
            eng.total_feature_uses += 1
            feature = event.properties.get("feature_name")
            if feature and feature not in eng.unique_features_used:
                eng.unique_features_used.append(feature)

        # Update engagement tier
        eng.tier = self._compute_engagement_tier(eng)

    def _update_session_window_counts(self, eng, now: datetime) -> None:
        """Update 7d and 30d session counts."""
        # Simple approximation — in production use a time-series store
        # Here we increment and let the analyzer recompute from full history
        eng.sessions_last_7d = min(eng.sessions_last_7d + 1, eng.total_sessions)
        eng.sessions_last_30d = min(eng.sessions_last_30d + 1, eng.total_sessions)

    def _compute_engagement_tier(self, eng) -> str:
        if eng.sessions_last_7d >= 5:
            return "power"
        if eng.sessions_last_7d >= 2:
            return "active"
        if eng.total_sessions >= 1:
            return "warming"
        return "cold"

    # ------------------------------------------------------------------
    # Interests
    # ------------------------------------------------------------------

    def _update_interests(self, event: Event, profile: BehavioralProfile) -> None:
        interests = profile.interests

        # Category from event properties
        category = event.properties.get("category")
        if category:
            interests.category_interests[category] = (
                interests.category_interests.get(category, 0) + 1
            )
            # Recompute top interests
            sorted_cats = sorted(
                interests.category_interests.items(),
                key=lambda x: x[1],
                reverse=True
            )
            interests.top_interests = [c for c, _ in sorted_cats[:5]]

        # Search terms
        if event.type == EventType.SEARCH_EXECUTED:
            query = event.properties.get("query", "").strip().lower()
            if query and query not in interests.search_terms:
                interests.search_terms.append(query)
                interests.search_terms = interests.search_terms[-50:]  # keep last 50

        # Item interactions
        item_id = event.properties.get("item_id") or event.target_id
        if item_id:
            if event.type == EventType.ITEM_VIEWED:
                if item_id not in interests.viewed_item_ids:
                    interests.viewed_item_ids.append(item_id)
                    interests.viewed_item_ids = interests.viewed_item_ids[-100:]
                interests.total_content_viewed += 1

            elif event.type == EventType.ITEM_SAVED:
                if item_id not in interests.saved_item_ids:
                    interests.saved_item_ids.append(item_id)

            elif event.type == EventType.ITEM_SHARED:
                if item_id not in interests.shared_item_ids:
                    interests.shared_item_ids.append(item_id)

        # Content
        if event.type == EventType.CONTENT_VIEWED:
            interests.total_content_viewed += 1
        if event.type == EventType.CONTENT_LIKED:
            interests.total_content_liked += 1

    # ------------------------------------------------------------------
    # RFM
    # ------------------------------------------------------------------

    def _update_rfm(self, event: Event, profile: BehavioralProfile) -> None:
        rfm = profile.rfm

        if event.type in MONETARY_EVENTS:
            rfm.total_conversions += 1
            rfm.days_since_last_conversion = 0.0

            # Extract monetary value
            amount = event.properties.get("amount", 0.0)
            if isinstance(amount, (int, float)) and amount > 0:
                rfm.total_monetary_value += amount
                rfm.avg_monetary_value = (
                    rfm.total_monetary_value / rfm.total_conversions
                )

            rfm.computed_at = event.timestamp
            rfm.segment = self._compute_rfm_segment(rfm)

    def _compute_rfm_segment(self, rfm) -> str:
        """Heuristic RFM segmentation."""
        if rfm.total_conversions == 0:
            return "new"
        if rfm.days_since_last_conversion is not None:
            if rfm.days_since_last_conversion > 90:
                return "lost"
            if rfm.days_since_last_conversion > 30:
                return "at_risk"
        if rfm.total_conversions >= 10:
            return "champions"
        if rfm.total_conversions >= 3:
            return "loyal"
        return "promising"

    # ------------------------------------------------------------------
    # Communication
    # ------------------------------------------------------------------

    def _update_communication(self, event: Event, profile: BehavioralProfile) -> None:
        comm = profile.communication
        now = event.timestamp

        if event.type == EventType.EMAIL_SENT:
            comm.email_sends += 1

        elif event.type == EventType.EMAIL_OPENED:
            if comm.email_sends > 0:
                comm.email_open_rate = min(
                    1.0,
                    (comm.email_open_rate * (comm.email_sends - 1) + 1.0) / comm.email_sends
                )
            self._record_hourly_engagement(comm, now)

        elif event.type == EventType.EMAIL_CLICKED:
            if comm.email_sends > 0:
                comm.email_click_rate = min(
                    1.0,
                    (comm.email_click_rate * (comm.email_sends - 1) + 1.0) / comm.email_sends
                )

        elif event.type == EventType.EMAIL_UNSUBSCRIBED:
            if "email" not in comm.unsubscribed_channels:
                comm.unsubscribed_channels.append("email")

        elif event.type == EventType.NOTIFICATION_SENT:
            comm.push_sends += 1

        elif event.type == EventType.NOTIFICATION_OPENED:
            if comm.push_sends > 0:
                comm.push_open_rate = min(
                    1.0,
                    (comm.push_open_rate * (comm.push_sends - 1) + 1.0) / comm.push_sends
                )
            self._record_hourly_engagement(comm, now)

        # Determine preferred channel
        rates = {}
        if "email" not in comm.unsubscribed_channels and comm.email_sends > 0:
            rates["email"] = comm.email_click_rate or comm.email_open_rate
        if "push" not in comm.unsubscribed_channels and comm.push_sends > 0:
            rates["push"] = comm.push_open_rate
        if rates:
            comm.preferred_channel = max(rates, key=rates.get)

    def _record_hourly_engagement(self, comm, timestamp: datetime) -> None:
        hour = timestamp.hour
        comm.hourly_engagement[hour] = comm.hourly_engagement.get(hour, 0) + 1
        # Best hour = hour with most engagement
        comm.best_hour = max(comm.hourly_engagement, key=comm.hourly_engagement.get)

        day = timestamp.strftime("%A")
        comm.daily_engagement[day] = comm.daily_engagement.get(day, 0) + 1
        comm.best_day = max(comm.daily_engagement, key=comm.daily_engagement.get)

    # ------------------------------------------------------------------
    # Churn signals
    # ------------------------------------------------------------------

    def _update_churn_signals(self, event: Event, profile: BehavioralProfile) -> None:
        churn = profile.churn
        churn.assessed_at = event.timestamp

        if event.type in FRICTION_EVENTS:
            churn.has_friction_events = True
            churn.recent_friction_count += 1

        if event.type == EventType.SUBSCRIPTION_CANCELLED:
            churn.cancelled_subscription = True

        if event.type in REACTIVATION_EVENTS:
            # Reset decay signals on reactivation
            churn.days_inactive = 0.0
            if churn.risk_level in ("medium", "high"):
                churn.risk_level = "low"
                churn.risk_score = max(0.0, churn.risk_score - 0.3)

        # Recompute risk score
        score = 0.0
        if churn.days_inactive > 60:
            score += 0.5
        elif churn.days_inactive > 30:
            score += 0.3
        elif churn.days_inactive > 14:
            score += 0.1

        if churn.has_friction_events:
            score += min(0.3, churn.recent_friction_count * 0.1)

        if churn.cancelled_subscription:
            score += 0.4

        churn.risk_score = min(1.0, score)
        churn.risk_level = self._risk_level(churn.risk_score)

    def _risk_level(self, score: float) -> str:
        if score >= 0.8:
            return "critical"
        if score >= 0.5:
            return "high"
        if score >= 0.25:
            return "medium"
        return "low"

    # ------------------------------------------------------------------
    # Intent signals
    # ------------------------------------------------------------------

    def _update_intent_signals(self, event: Event, profile: BehavioralProfile) -> None:

        # Purchase intent
        if event.type in PURCHASE_INTENT_EVENTS:
            existing = profile.get_intent_signal("purchase_intent")
            current_strength = existing.strength if existing else 0.0
            new_strength = min(1.0, current_strength + 0.2)
            profile.set_intent_signal(IntentSignal(
                signal_type="purchase_intent",
                strength=new_strength,
                detected_at=event.timestamp,
                triggering_events=[event.type.value],
            ))

        # Referral intent
        if event.type in {EventType.ITEM_SHARED, EventType.INVITE_SENT}:
            profile.set_intent_signal(IntentSignal(
                signal_type="referral_intent",
                strength=0.8,
                detected_at=event.timestamp,
                triggering_events=[event.type.value],
            ))

        # Upsell signal
        if event.type in {EventType.FEATURE_USED, EventType.SUBSCRIPTION_UPGRADED}:
            existing = profile.get_intent_signal("upsell_ready")
            current_strength = existing.strength if existing else 0.0
            new_strength = min(1.0, current_strength + 0.15)
            profile.set_intent_signal(IntentSignal(
                signal_type="upsell_ready",
                strength=new_strength,
                detected_at=event.timestamp,
                triggering_events=[event.type.value],
            ))

        # Review intent — happy path signals
        if event.type in {EventType.ORDER_COMPLETED, EventType.PAYMENT_COMPLETED}:
            profile.set_intent_signal(IntentSignal(
                signal_type="review_intent",
                strength=0.7,
                detected_at=event.timestamp,
                triggering_events=[event.type.value],
            ))
