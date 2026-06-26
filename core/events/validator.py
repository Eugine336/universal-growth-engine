"""
Event Validator

Validates incoming events against:
1. Schema constraints (handled by Pydantic on the Event model)
2. Application-level rules (is this event type allowed for this application?)
3. Required property rules (does this event type need specific properties?)
4. Rate limiting (is this actor sending too many events?)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from .schema import Event, EventType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Required properties per event type
# ---------------------------------------------------------------------------

REQUIRED_PROPERTIES: Dict[str, List[str]] = {
    EventType.PAGE_VIEWED: ["page_url"],
    EventType.ITEM_VIEWED: ["item_id"],
    EventType.SEARCH_EXECUTED: ["query"],
    EventType.PAYMENT_COMPLETED: ["amount", "currency"],
    EventType.PAYMENT_FAILED: ["amount", "currency", "reason"],
    EventType.ORDER_CREATED: ["order_id", "amount"],
    EventType.ORDER_COMPLETED: ["order_id"],
    EventType.REVIEW_CREATED: ["rating"],
    EventType.REFERRAL_SENT: ["referral_code"],
    EventType.REFERRAL_CONVERTED: ["referral_code", "referred_entity_id"],
    EventType.DISPUTE_OPENED: ["reason"],
    EventType.KYC_COMPLETED: ["verification_method"],
    EventType.SUBSCRIPTION_STARTED: ["plan_id"],
    EventType.SUBSCRIPTION_CANCELLED: ["reason"],
    EventType.CUSTOM: ["custom_type"],
}


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add_error(self, msg: str) -> "ValidationResult":
        self.errors.append(msg)
        self.valid = False
        return self

    def add_warning(self, msg: str) -> "ValidationResult":
        self.warnings.append(msg)
        return self


# ---------------------------------------------------------------------------
# Application event policy
# ---------------------------------------------------------------------------

@dataclass
class ApplicationEventPolicy:
    """
    Defines which event types an application is allowed to emit.
    If allowed_events is empty, all event types are permitted.
    """
    application_id: str
    allowed_events: Set[str] = field(default_factory=set)
    blocked_events: Set[str] = field(default_factory=set)
    require_actor: bool = True
    max_properties_size_bytes: int = 65536  # 64KB


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

class EventValidator:
    """
    Validates events before they enter the processing pipeline.

    Usage:
        validator = EventValidator()
        validator.register_policy(policy)
        result = validator.validate(event)
    """

    def __init__(self):
        self._policies: Dict[str, ApplicationEventPolicy] = {}

    def register_policy(self, policy: ApplicationEventPolicy) -> None:
        self._policies[policy.application_id] = policy
        logger.info(f"Registered event policy for application: {policy.application_id}")

    def validate(self, event: Event) -> ValidationResult:
        result = ValidationResult(valid=True)

        self._validate_application(event, result)
        self._validate_actor(event, result)
        self._validate_required_properties(event, result)
        self._validate_custom_type(event, result)
        self._validate_timestamp(event, result)
        self._validate_properties_size(event, result)

        if not result.valid:
            logger.warning(
                f"Event validation failed | app={event.application_id} "
                f"type={event.type} errors={result.errors}"
            )

        return result

    # ------------------------------------------------------------------
    # Internal validators
    # ------------------------------------------------------------------

    def _validate_application(self, event: Event, result: ValidationResult) -> None:
        if not event.application_id or not event.application_id.strip():
            result.add_error("application_id is required")
            return

        policy = self._policies.get(event.application_id)
        if policy is None:
            # No policy registered — permissive by default, but warn
            result.add_warning(
                f"No event policy registered for application '{event.application_id}'. "
                f"All events permitted."
            )
            return

        event_type_str = event.type.value

        if policy.blocked_events and event_type_str in policy.blocked_events:
            result.add_error(
                f"Event type '{event_type_str}' is blocked for application "
                f"'{event.application_id}'"
            )

        if policy.allowed_events and event_type_str not in policy.allowed_events:
            result.add_error(
                f"Event type '{event_type_str}' is not in the allowed list for "
                f"application '{event.application_id}'"
            )

    def _validate_actor(self, event: Event, result: ValidationResult) -> None:
        policy = self._policies.get(event.application_id)
        if policy and policy.require_actor:
            if not event.actor_id:
                # System events are exempt
                if event.source.value != "system":
                    result.add_warning(
                        f"Event type '{event.type.value}' has no actor_id. "
                        f"Identity resolution may fail."
                    )

    def _validate_required_properties(self, event: Event, result: ValidationResult) -> None:
        required = REQUIRED_PROPERTIES.get(event.type.value, [])
        for prop in required:
            if prop not in event.properties or event.properties[prop] is None:
                result.add_error(
                    f"Missing required property '{prop}' for event type '{event.type.value}'"
                )

    def _validate_custom_type(self, event: Event, result: ValidationResult) -> None:
        if event.type == EventType.CUSTOM:
            if not event.custom_type:
                result.add_error("custom_type must be set when event type is CUSTOM")
            elif not event.custom_type.replace("_", "").isalnum():
                result.add_error(
                    "custom_type must be alphanumeric with underscores only "
                    "(e.g. ESCROW_RELEASED)"
                )

    def _validate_timestamp(self, event: Event, result: ValidationResult) -> None:
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        # Reject events more than 24h in the future
        if event.timestamp > now + timedelta(hours=24):
            result.add_error(
                f"Event timestamp is too far in the future: {event.timestamp}"
            )
        # Warn on events older than 7 days
        if event.timestamp < now - timedelta(days=7):
            result.add_warning(
                f"Event timestamp is more than 7 days old: {event.timestamp}. "
                f"Behavioral impact may be reduced."
            )

    def _validate_properties_size(self, event: Event, result: ValidationResult) -> None:
        import json
        policy = self._policies.get(event.application_id)
        limit = policy.max_properties_size_bytes if policy else 65536
        try:
            size = len(json.dumps(event.properties).encode("utf-8"))
            if size > limit:
                result.add_error(
                    f"Event properties size ({size} bytes) exceeds limit ({limit} bytes)"
                )
        except Exception:
            result.add_warning("Could not calculate properties size.")
