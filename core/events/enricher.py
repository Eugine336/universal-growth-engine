"""
Event Enricher

Enriches raw events with additional computed context before
they are routed to downstream consumers.

Enrichment includes:
- Server receipt timestamp
- Derived event category and subcategory
- Inferred intent signals
- UTM normalization
- IP geolocation (stubbed — plug in real provider)
- User agent parsing (stubbed — plug in real provider)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from .schema import Event, EventType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event category mapping
# ---------------------------------------------------------------------------

EVENT_CATEGORY: dict[str, str] = {
    # Lifecycle
    EventType.ENTITY_CREATED: "lifecycle",
    EventType.ENTITY_UPDATED: "lifecycle",
    EventType.ENTITY_DELETED: "lifecycle",

    # Identity
    EventType.USER_REGISTERED: "identity",
    EventType.USER_VERIFIED: "identity",
    EventType.LOGIN_SUCCESS: "identity",
    EventType.LOGIN_FAILED: "identity",
    EventType.PASSWORD_RESET: "identity",
    EventType.ACCOUNT_DEACTIVATED: "identity",

    # Engagement
    EventType.SESSION_STARTED: "engagement",
    EventType.SESSION_ENDED: "engagement",
    EventType.PAGE_VIEWED: "engagement",
    EventType.FEATURE_USED: "engagement",
    EventType.SEARCH_EXECUTED: "engagement",
    EventType.ITEM_VIEWED: "engagement",
    EventType.ITEM_SAVED: "engagement",
    EventType.ITEM_SHARED: "engagement",

    # Communication
    EventType.MESSAGE_SENT: "communication",
    EventType.MESSAGE_READ: "communication",
    EventType.NOTIFICATION_SENT: "communication",
    EventType.NOTIFICATION_OPENED: "communication",
    EventType.EMAIL_SENT: "communication",
    EventType.EMAIL_OPENED: "communication",
    EventType.EMAIL_CLICKED: "communication",
    EventType.EMAIL_BOUNCED: "communication",
    EventType.EMAIL_UNSUBSCRIBED: "communication",

    # Transaction
    EventType.OFFER_MADE: "transaction",
    EventType.OFFER_ACCEPTED: "transaction",
    EventType.OFFER_REJECTED: "transaction",
    EventType.ORDER_CREATED: "transaction",
    EventType.ORDER_COMPLETED: "transaction",
    EventType.ORDER_CANCELLED: "transaction",
    EventType.PAYMENT_INITIATED: "transaction",
    EventType.PAYMENT_COMPLETED: "transaction",
    EventType.PAYMENT_FAILED: "transaction",
    EventType.REFUND_INITIATED: "transaction",
    EventType.REFUND_COMPLETED: "transaction",

    # Subscription
    EventType.SUBSCRIPTION_STARTED: "subscription",
    EventType.SUBSCRIPTION_RENEWED: "subscription",
    EventType.SUBSCRIPTION_CANCELLED: "subscription",
    EventType.SUBSCRIPTION_UPGRADED: "subscription",
    EventType.SUBSCRIPTION_DOWNGRADED: "subscription",

    # Trust
    EventType.REVIEW_CREATED: "trust",
    EventType.REVIEW_RESPONDED: "trust",
    EventType.DISPUTE_OPENED: "trust",
    EventType.DISPUTE_RESOLVED: "trust",
    EventType.FLAG_SUBMITTED: "trust",
    EventType.KYC_STARTED: "trust",
    EventType.KYC_COMPLETED: "trust",
    EventType.KYC_FAILED: "trust",

    # Growth
    EventType.REFERRAL_SENT: "growth",
    EventType.REFERRAL_CONVERTED: "growth",
    EventType.INVITE_SENT: "growth",
    EventType.INVITE_ACCEPTED: "growth",

    # Content
    EventType.CONTENT_CREATED: "content",
    EventType.CONTENT_PUBLISHED: "content",
    EventType.CONTENT_VIEWED: "content",
    EventType.CONTENT_LIKED: "content",

    EventType.CUSTOM: "custom",
}

# High-value events that strongly indicate purchase intent or conversion
HIGH_INTENT_EVENTS = {
    EventType.OFFER_MADE,
    EventType.ORDER_CREATED,
    EventType.PAYMENT_INITIATED,
    EventType.SUBSCRIPTION_STARTED,
    EventType.KYC_STARTED,
    EventType.SEARCH_EXECUTED,
    EventType.ITEM_SAVED,
}

# Negative signals — churn / friction indicators
FRICTION_EVENTS = {
    EventType.LOGIN_FAILED,
    EventType.PAYMENT_FAILED,
    EventType.ORDER_CANCELLED,
    EventType.DISPUTE_OPENED,
    EventType.EMAIL_UNSUBSCRIBED,
    EventType.ACCOUNT_DEACTIVATED,
    EventType.REFUND_INITIATED,
    EventType.SUBSCRIPTION_CANCELLED,
}

# Conversion events — completed value exchange
CONVERSION_EVENTS = {
    EventType.PAYMENT_COMPLETED,
    EventType.ORDER_COMPLETED,
    EventType.OFFER_ACCEPTED,
    EventType.SUBSCRIPTION_STARTED,
    EventType.SUBSCRIPTION_RENEWED,
    EventType.KYC_COMPLETED,
    EventType.REFERRAL_CONVERTED,
    EventType.INVITE_ACCEPTED,
}


class EventEnricher:
    """
    Enriches validated events with computed metadata before routing.

    Enrichment is additive — it writes into event.properties under
    a reserved '_ugie' namespace to avoid colliding with app properties.
    """

    def enrich(self, event: Event) -> Event:
        """Run all enrichment steps on the event. Returns the mutated event."""
        self._stamp_receipt(event)
        self._set_category(event)
        self._set_intent_signals(event)
        self._normalize_utm(event)
        self._extract_session_depth(event)
        logger.debug(
            f"Enriched event | id={event.id} type={event.type.value} "
            f"category={event.properties.get('_ugie', {}).get('category')}"
        )
        return event

    # ------------------------------------------------------------------
    # Enrichment steps
    # ------------------------------------------------------------------

    def _stamp_receipt(self, event: Event) -> None:
        if not event.received_at:
            event.received_at = datetime.now(timezone.utc)
        self._ugie(event)["received_at"] = event.received_at.isoformat()

    def _set_category(self, event: Event) -> None:
        category = EVENT_CATEGORY.get(event.type, "unknown")
        ugie = self._ugie(event)
        ugie["category"] = category
        ugie["effective_type"] = event.effective_type()

    def _set_intent_signals(self, event: Event) -> None:
        ugie = self._ugie(event)
        ugie["is_high_intent"] = event.type in HIGH_INTENT_EVENTS
        ugie["is_friction"] = event.type in FRICTION_EVENTS
        ugie["is_conversion"] = event.type in CONVERSION_EVENTS

    def _normalize_utm(self, event: Event) -> None:
        """Normalize UTM params to lowercase and strip whitespace."""
        ctx = event.context
        ugie = self._ugie(event)
        utm = {}
        if ctx.utm_source:
            utm["source"] = ctx.utm_source.strip().lower()
        if ctx.utm_medium:
            utm["medium"] = ctx.utm_medium.strip().lower()
        if ctx.utm_campaign:
            utm["campaign"] = ctx.utm_campaign.strip().lower()
        if ctx.utm_content:
            utm["content"] = ctx.utm_content.strip().lower()
        if ctx.utm_term:
            utm["term"] = ctx.utm_term.strip().lower()
        if utm:
            ugie["utm"] = utm

    def _extract_session_depth(self, event: Event) -> None:
        """
        Track page depth within a session.
        The session depth counter is maintained externally (e.g. in Redis).
        Here we just flag whether a session_id is present.
        """
        ugie = self._ugie(event)
        ugie["has_session"] = bool(event.context.session_id)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ugie(self, event: Event) -> dict:
        """Access or create the _ugie metadata namespace in event.properties."""
        if "_ugie" not in event.properties:
            event.properties["_ugie"] = {}
        return event.properties["_ugie"]
