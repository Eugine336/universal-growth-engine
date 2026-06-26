"""
Universal Event Schema

Every interaction across every application flows through this schema.
The engine processes events — not pages, not APIs, not endpoints.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator


class EventType(str, Enum):
    """
    Universal event types understood by the engine.
    Applications may emit additional domain-specific events
    via the CUSTOM type with a custom_type string.
    """

    # --- Lifecycle ---
    ENTITY_CREATED = "ENTITY_CREATED"
    ENTITY_UPDATED = "ENTITY_UPDATED"
    ENTITY_DELETED = "ENTITY_DELETED"

    # --- Identity & Auth ---
    USER_REGISTERED = "USER_REGISTERED"
    USER_VERIFIED = "USER_VERIFIED"
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILED = "LOGIN_FAILED"
    PASSWORD_RESET = "PASSWORD_RESET"
    ACCOUNT_DEACTIVATED = "ACCOUNT_DEACTIVATED"

    # --- Session & Engagement ---
    SESSION_STARTED = "SESSION_STARTED"
    SESSION_ENDED = "SESSION_ENDED"
    PAGE_VIEWED = "PAGE_VIEWED"
    FEATURE_USED = "FEATURE_USED"
    SEARCH_EXECUTED = "SEARCH_EXECUTED"
    ITEM_VIEWED = "ITEM_VIEWED"
    ITEM_SAVED = "ITEM_SAVED"
    ITEM_SHARED = "ITEM_SHARED"

    # --- Communication ---
    MESSAGE_SENT = "MESSAGE_SENT"
    MESSAGE_READ = "MESSAGE_READ"
    NOTIFICATION_SENT = "NOTIFICATION_SENT"
    NOTIFICATION_OPENED = "NOTIFICATION_OPENED"
    EMAIL_SENT = "EMAIL_SENT"
    EMAIL_OPENED = "EMAIL_OPENED"
    EMAIL_CLICKED = "EMAIL_CLICKED"
    EMAIL_BOUNCED = "EMAIL_BOUNCED"
    EMAIL_UNSUBSCRIBED = "EMAIL_UNSUBSCRIBED"

    # --- Transactions ---
    OFFER_MADE = "OFFER_MADE"
    OFFER_ACCEPTED = "OFFER_ACCEPTED"
    OFFER_REJECTED = "OFFER_REJECTED"
    ORDER_CREATED = "ORDER_CREATED"
    ORDER_COMPLETED = "ORDER_COMPLETED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    PAYMENT_INITIATED = "PAYMENT_INITIATED"
    PAYMENT_COMPLETED = "PAYMENT_COMPLETED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    REFUND_INITIATED = "REFUND_INITIATED"
    REFUND_COMPLETED = "REFUND_COMPLETED"

    # --- Subscriptions ---
    SUBSCRIPTION_STARTED = "SUBSCRIPTION_STARTED"
    SUBSCRIPTION_RENEWED = "SUBSCRIPTION_RENEWED"
    SUBSCRIPTION_CANCELLED = "SUBSCRIPTION_CANCELLED"
    SUBSCRIPTION_UPGRADED = "SUBSCRIPTION_UPGRADED"
    SUBSCRIPTION_DOWNGRADED = "SUBSCRIPTION_DOWNGRADED"

    # --- Trust & Quality ---
    REVIEW_CREATED = "REVIEW_CREATED"
    REVIEW_RESPONDED = "REVIEW_RESPONDED"
    DISPUTE_OPENED = "DISPUTE_OPENED"
    DISPUTE_RESOLVED = "DISPUTE_RESOLVED"
    FLAG_SUBMITTED = "FLAG_SUBMITTED"
    KYC_STARTED = "KYC_STARTED"
    KYC_COMPLETED = "KYC_COMPLETED"
    KYC_FAILED = "KYC_FAILED"

    # --- Referral & Growth ---
    REFERRAL_SENT = "REFERRAL_SENT"
    REFERRAL_CONVERTED = "REFERRAL_CONVERTED"
    INVITE_SENT = "INVITE_SENT"
    INVITE_ACCEPTED = "INVITE_ACCEPTED"

    # --- Content ---
    CONTENT_CREATED = "CONTENT_CREATED"
    CONTENT_PUBLISHED = "CONTENT_PUBLISHED"
    CONTENT_VIEWED = "CONTENT_VIEWED"
    CONTENT_LIKED = "CONTENT_LIKED"

    # --- Domain-Specific (pass-through) ---
    CUSTOM = "CUSTOM"


class EventSource(str, Enum):
    """Where the event originated."""
    WEB = "web"
    MOBILE_IOS = "mobile_ios"
    MOBILE_ANDROID = "mobile_android"
    API = "api"
    SYSTEM = "system"
    WEBHOOK = "webhook"
    INTEGRATION = "integration"


class GeoContext(BaseModel):
    """Geographic context attached to an event."""
    country: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timezone: Optional[str] = None


class DeviceContext(BaseModel):
    """Device context attached to an event."""
    device_id: Optional[str] = None
    device_type: Optional[str] = None       # mobile | tablet | desktop
    os: Optional[str] = None
    os_version: Optional[str] = None
    browser: Optional[str] = None
    browser_version: Optional[str] = None
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None


class EventContext(BaseModel):
    """Full context envelope for an event."""
    session_id: Optional[str] = None
    device: Optional[DeviceContext] = None
    geo: Optional[GeoContext] = None
    referrer: Optional[str] = None
    utm_source: Optional[str] = None
    utm_medium: Optional[str] = None
    utm_campaign: Optional[str] = None
    utm_content: Optional[str] = None
    utm_term: Optional[str] = None
    experiment_id: Optional[str] = None
    variant_id: Optional[str] = None


class Event(BaseModel):
    """
    The universal event — the atomic unit of everything the engine processes.

    Every interaction across every application reduces to an Event.
    """

    # Identity
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    application_id: str = Field(..., description="Which application emitted this event")

    # What happened
    type: EventType = Field(..., description="The event type")
    custom_type: Optional[str] = Field(
        None,
        description="Custom event type name when type=CUSTOM"
    )

    # Who did it
    actor_id: Optional[str] = Field(
        None,
        description="Entity ID of the actor (user, system, etc.)"
    )
    actor_type: Optional[str] = Field(
        None,
        description="Entity type of the actor (User, Seller, Trader, etc.)"
    )

    # What it was done to
    target_id: Optional[str] = Field(
        None,
        description="Entity ID of the target (product, listing, account, etc.)"
    )
    target_type: Optional[str] = Field(
        None,
        description="Entity type of the target"
    )

    # Payload
    properties: Dict[str, Any] = Field(
        default_factory=dict,
        description="Domain-specific event properties"
    )

    # Context
    source: EventSource = Field(EventSource.API)
    context: EventContext = Field(default_factory=EventContext)

    # Timing
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    received_at: Optional[datetime] = None

    # Internal tracking
    identity_id: Optional[str] = Field(
        None,
        description="Resolved identity ID — set by identity layer after resolution"
    )
    processed: bool = False
    processing_errors: list[str] = Field(default_factory=list)

    @field_validator("custom_type")
    @classmethod
    def custom_type_required_when_custom(cls, v, info):
        if info.data.get("type") == EventType.CUSTOM and not v:
            raise ValueError("custom_type is required when type is CUSTOM")
        return v

    def effective_type(self) -> str:
        """Returns the effective event type string for routing and processing."""
        if self.type == EventType.CUSTOM:
            return f"CUSTOM:{self.custom_type}"
        return self.type.value

    def mark_received(self) -> "Event":
        """Stamp the server receipt time."""
        self.received_at = datetime.now(timezone.utc)
        return self

    def mark_processed(self) -> "Event":
        self.processed = True
        return self

    def add_error(self, error: str) -> "Event":
        self.processing_errors.append(error)
        return self

    model_config = {"use_enum_values": False}
