"""
Event Bus

The central nervous system of the UGIE engine.

Every event flows through the bus:
    receive → validate → enrich → route → mark processed

The bus is the single entry point for all event ingestion.
Applications submit events here. The bus does the rest.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .enricher import EventEnricher
from .router import EventRouter, EventHandler
from .schema import Event, EventType
from .validator import EventValidator, ApplicationEventPolicy, ValidationResult

logger = logging.getLogger(__name__)


@dataclass
class ProcessingResult:
    """Result of submitting an event to the bus."""
    event_id: str
    success: bool
    validation: Optional[ValidationResult] = None
    delivered_to: int = 0
    delivery_errors: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    processed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict:
        return {
            "event_id": self.event_id,
            "success": self.success,
            "delivered_to": self.delivered_to,
            "delivery_errors": self.delivery_errors,
            "errors": self.errors,
            "warnings": self.warnings,
            "processed_at": self.processed_at.isoformat(),
        }


class EventBus:
    """
    The UGIE Event Bus.

    Single entry point for all event ingestion across all applications.

    Usage:
        bus = EventBus()

        # Register an application policy
        bus.register_application(ApplicationEventPolicy(
            application_id="ucmc",
            require_actor=True,
        ))

        # Subscribe a downstream consumer
        bus.subscribe(
            consumer_id="identity_layer",
            handler=identity_handler,
            event_types={"USER_REGISTERED", "LOGIN_SUCCESS"},
        )

        # Submit an event
        event = Event(
            application_id="ucmc",
            type=EventType.USER_REGISTERED,
            actor_id="user_123",
            actor_type="Buyer",
            properties={"email": "user@example.com"},
        )
        result = bus.submit(event)
    """

    def __init__(
        self,
        validator: Optional[EventValidator] = None,
        enricher: Optional[EventEnricher] = None,
        router: Optional[EventRouter] = None,
    ):
        self._validator = validator or EventValidator()
        self._enricher = enricher or EventEnricher()
        self._router = router or EventRouter()

        # Metrics
        self._total_received: int = 0
        self._total_processed: int = 0
        self._total_failed: int = 0

        # Internal event log (bounded ring buffer for debug — not a DB)
        self._recent_events: List[Event] = []
        self._max_recent: int = 500

        logger.info("EventBus initialized")

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def register_application(self, policy: ApplicationEventPolicy) -> None:
        """Register an application event policy."""
        self._validator.register_policy(policy)
        logger.info(f"Application registered on EventBus: {policy.application_id}")

    def subscribe(
        self,
        consumer_id: str,
        handler: EventHandler,
        event_types: Optional[set] = None,
        categories: Optional[set] = None,
        application_ids: Optional[set] = None,
    ) -> None:
        """Subscribe a downstream consumer to events."""
        self._router.subscribe(
            consumer_id=consumer_id,
            handler=handler,
            event_types=event_types,
            categories=categories,
            application_ids=application_ids,
        )

    def unsubscribe(self, consumer_id: str) -> None:
        self._router.unsubscribe(consumer_id)

    # ------------------------------------------------------------------
    # Core pipeline
    # ------------------------------------------------------------------

    def submit(self, event: Event) -> ProcessingResult:
        """
        Submit an event into the pipeline.

        Pipeline:
            receive → validate → enrich → route → mark processed
        """
        self._total_received += 1
        event.mark_received()

        result = ProcessingResult(event_id=event.id, success=False)

        # 1. Validate
        validation = self._validator.validate(event)
        result.validation = validation
        result.warnings.extend(validation.warnings)

        if not validation.valid:
            result.errors.extend(validation.errors)
            self._total_failed += 1
            logger.warning(
                f"Event rejected | id={event.id} type={event.type.value} "
                f"errors={validation.errors}"
            )
            return result

        # 2. Enrich
        try:
            self._enricher.enrich(event)
        except Exception as e:
            logger.error(f"Enrichment failed for event {event.id}: {e}")
            result.errors.append(f"Enrichment error: {str(e)}")
            # Non-fatal — continue to routing

        # 3. Route
        errors_before_routing = len(event.processing_errors)
        delivered = self._router.route(event)
        result.delivered_to = delivered

        # Surface routing errors
        routing_errors = event.processing_errors[errors_before_routing:]
        if routing_errors:
            result.delivery_errors = len(routing_errors)
            result.warnings.extend(routing_errors)

        # 4. Mark processed
        event.mark_processed()
        result.success = True
        self._total_processed += 1

        # 5. Store in recent buffer
        self._store_recent(event)

        logger.info(
            f"Event processed | id={event.id} type={event.type.value} "
            f"app={event.application_id} delivered_to={delivered}"
        )

        return result

    def submit_batch(self, events: List[Event]) -> List[ProcessingResult]:
        """Submit multiple events. Returns one result per event."""
        return [self.submit(event) for event in events]

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def stats(self) -> Dict:
        return {
            "total_received": self._total_received,
            "total_processed": self._total_processed,
            "total_failed": self._total_failed,
            "success_rate": (
                round(self._total_processed / self._total_received, 4)
                if self._total_received > 0 else None
            ),
            "router": self._router.stats(),
            "recent_event_count": len(self._recent_events),
        }

    def recent_events(
        self,
        application_id: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Event]:
        events = self._recent_events
        if application_id:
            events = [e for e in events if e.application_id == application_id]
        if event_type:
            events = [e for e in events if e.type.value == event_type]
        return events[-limit:]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _store_recent(self, event: Event) -> None:
        self._recent_events.append(event)
        if len(self._recent_events) > self._max_recent:
            self._recent_events = self._recent_events[-self._max_recent:]
