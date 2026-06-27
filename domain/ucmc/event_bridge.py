"""
UCMC → UGIE Event Bridge

Maps UCMC signalRegistry signals to UGIE EventType events.
Used by the UCMC backend to translate platform signals into
UGIE event payloads before POSTing to /api/v1/events.

In production, this runs as a queue consumer or middleware in
UCMC's Node.js backend. This Python reference exists for
documentation and testing purposes.

Usage:
    from domain.ucmc.event_bridge import build_ugie_event

    ugie_payload = build_ugie_event(
        signal_type="LISTING_CREATE",
        actor_id="seller_abc",
        actor_type="Seller",
        target_id="listing_xyz",
        properties={"title": "AI Logo Design", "category": "CREATIVE", "price": 50},
    )
    # POST ugie_payload to UGIE /api/v1/events
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

SIGNAL_TO_UGIE_EVENT: Dict[str, Dict[str, Any]] = {
    "INIT": {
        "type": "USER_REGISTERED",
    },
    "PROFILE_UPDATE": {
        "type": "ENTITY_UPDATED",
    },
    "LISTING_CREATE": {
        "type": "CONTENT_CREATED",
        "target_type": "Listing",
    },
    "LISTING_UPDATE": {
        "type": "ENTITY_UPDATED",
        "target_type": "Listing",
    },
    "MESSAGE_SEND": {
        "type": "MESSAGE_SENT",
    },
    "DELIVERY_CONFIRM": {
        "type": "ORDER_COMPLETED",
    },
    "REVIEW_SUBMIT": {
        "type": "REVIEW_CREATED",
    },
    "KYC_START": {
        "type": "KYC_STARTED",
    },
    "KYC_VERIFIED": {
        "type": "KYC_COMPLETED",
    },
    "KYC_REJECTED": {
        "type": "CUSTOM",
        "custom_type": "KYC_REJECTED",
    },
    "PAYMENT_INITIATE": {
        "type": "PAYMENT_INITIATED",
    },
    "LOCK": {
        "type": "PAYMENT_INITIATED",
        "extra_properties": {"escrow": True},
    },
    "RELEASE": {
        "type": "PAYMENT_COMPLETED",
        "extra_properties": {"escrow_released": True},
    },
    "REVERT": {
        "type": "REFUND_COMPLETED",
        "extra_properties": {"escrow_reverted": True},
    },
    "FINALIZE": {
        "type": "ORDER_COMPLETED",
        "extra_properties": {"escrow_finalized": True},
    },
    "DISPUTE_OPEN": {
        "type": "DISPUTE_OPENED",
    },
    "DISPUTE_VOTE": {
        "type": "CUSTOM",
        "custom_type": "DISPUTE_VOTE",
    },
    "DISPUTE_RESOLVE": {
        "type": "DISPUTE_RESOLVED",
    },
    "EMAIL_VERIFIED": {
        "type": "USER_VERIFIED",
    },
    "ONBOARDING_COMPLETE": {
        "type": "CUSTOM",
        "custom_type": "ONBOARDING_COMPLETE",
    },
    "DEPOSIT_CONFIRMED": {
        "type": "CUSTOM",
        "custom_type": "DEPOSIT_CONFIRMED",
    },
    "WITHDRAWAL_REQUEST": {
        "type": "CUSTOM",
        "custom_type": "WITHDRAWAL_REQUEST",
    },
    "REPORT_ACTOR": {
        "type": "FLAG_SUBMITTED",
    },
    "ACTOR_BANNED": {
        "type": "ACCOUNT_DEACTIVATED",
    },
    "SANCTIONS_HIT": {
        "type": "CUSTOM",
        "custom_type": "SANCTIONS_HIT",
    },
}

APPLICATION_ID = "ucmc_marketplace"


def build_ugie_event(
    signal_type: str,
    actor_id: str,
    actor_type: str = "Buyer",
    target_id: Optional[str] = None,
    properties: Optional[Dict[str, Any]] = None,
    source: str = "api",
) -> Optional[Dict[str, Any]]:
    """
    Translate a UCMC signal into a UGIE event payload.

    Returns None if the signal type has no mapping.

    Args:
        signal_type: UCMC signal name (e.g. "LISTING_CREATE", "LOCK")
        actor_id: ID of the actor (buyer/seller public key or internal ID)
        actor_type: Entity type of the actor ("Buyer" or "Seller")
        target_id: Optional target entity ID (listing, escrow, etc.)
        properties: Signal payload properties
        source: Event source ("api", "web", "webhook", etc.)

    Returns:
        Dict ready to POST to UGIE /api/v1/events, or None.
    """
    mapping = SIGNAL_TO_UGIE_EVENT.get(signal_type)
    if mapping is None:
        return None

    event_properties = dict(properties or {})

    extra = mapping.get("extra_properties")
    if extra:
        event_properties.update(extra)

    event: Dict[str, Any] = {
        "application_id": APPLICATION_ID,
        "type": mapping["type"],
        "actor_id": actor_id,
        "actor_type": actor_type,
        "source": source,
        "properties": event_properties,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    custom_type = mapping.get("custom_type")
    if custom_type:
        event["custom_type"] = custom_type

    target_type = mapping.get("target_type")
    if target_id:
        event["target_id"] = target_id
    if target_type:
        event["target_type"] = target_type

    return event
