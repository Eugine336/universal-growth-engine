"""
Event Router

Routes enriched events to registered downstream consumers.

Consumers register interest in specific event types or categories.
The router delivers events to all matching consumers.

Design:
- Sync consumers run in the same thread (lightweight handlers)
- Async consumers are dispatched to a queue (heavy processing)
- Wildcard subscription supported via EventType.* or category.*
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Callable, Dict, List, Optional, Set

from .schema import Event, EventType

logger = logging.getLogger(__name__)

# Consumer callable type
EventHandler = Callable[[Event], None]


class Subscription:
    """Represents a single consumer subscription."""

    def __init__(
        self,
        consumer_id: str,
        handler: EventHandler,
        event_types: Optional[Set[str]] = None,
        categories: Optional[Set[str]] = None,
        application_ids: Optional[Set[str]] = None,
    ):
        self.consumer_id = consumer_id
        self.handler = handler
        # None means "all"
        self.event_types = event_types
        self.categories = categories
        self.application_ids = application_ids

    def matches(self, event: Event) -> bool:
        """Returns True if this subscription should receive the event."""
        # Application filter
        if self.application_ids and event.application_id not in self.application_ids:
            return False

        # Event type filter
        if self.event_types and event.type.value not in self.event_types:
            # Check category filter as fallback
            if self.categories:
                category = event.properties.get("_ugie", {}).get("category")
                return category in self.categories
            return False

        # Category filter (if no event_types filter)
        if self.categories and not self.event_types:
            category = event.properties.get("_ugie", {}).get("category")
            return category in self.categories

        return True


class EventRouter:
    """
    Routes events to registered downstream consumers.

    Usage:
        router = EventRouter()

        # Subscribe to specific event types
        router.subscribe(
            consumer_id="identity_layer",
            handler=identity_handler,
            event_types={"USER_REGISTERED", "LOGIN_SUCCESS"}
        )

        # Subscribe to all events
        router.subscribe(
            consumer_id="audit_log",
            handler=audit_handler,
        )

        # Route an event
        router.route(event)
    """

    def __init__(self):
        self._subscriptions: List[Subscription] = []
        self._delivery_counts: Dict[str, int] = defaultdict(int)
        self._error_counts: Dict[str, int] = defaultdict(int)

    def subscribe(
        self,
        consumer_id: str,
        handler: EventHandler,
        event_types: Optional[Set[str]] = None,
        categories: Optional[Set[str]] = None,
        application_ids: Optional[Set[str]] = None,
    ) -> None:
        """Register a consumer subscription."""
        sub = Subscription(
            consumer_id=consumer_id,
            handler=handler,
            event_types=event_types,
            categories=categories,
            application_ids=application_ids,
        )
        self._subscriptions.append(sub)
        logger.info(
            f"Subscribed consumer '{consumer_id}' | "
            f"event_types={event_types} categories={categories} "
            f"application_ids={application_ids}"
        )

    def unsubscribe(self, consumer_id: str) -> None:
        """Remove all subscriptions for a consumer."""
        before = len(self._subscriptions)
        self._subscriptions = [
            s for s in self._subscriptions if s.consumer_id != consumer_id
        ]
        removed = before - len(self._subscriptions)
        logger.info(f"Unsubscribed consumer '{consumer_id}' ({removed} subscriptions removed)")

    def route(self, event: Event) -> int:
        """
        Deliver the event to all matching consumers.
        Returns the number of consumers the event was delivered to.
        """
        delivered = 0
        for sub in self._subscriptions:
            if sub.matches(event):
                try:
                    sub.handler(event)
                    self._delivery_counts[sub.consumer_id] += 1
                    delivered += 1
                except Exception as e:
                    self._error_counts[sub.consumer_id] += 1
                    logger.error(
                        f"Consumer '{sub.consumer_id}' failed to handle event "
                        f"id={event.id} type={event.type.value} | error={e}"
                    )
                    event.add_error(
                        f"Delivery failed to consumer '{sub.consumer_id}': {str(e)}"
                    )

        if delivered == 0:
            logger.debug(
                f"Event id={event.id} type={event.type.value} "
                f"had no matching consumers."
            )

        return delivered

    def stats(self) -> Dict:
        return {
            "subscriptions": len(self._subscriptions),
            "consumers": list({s.consumer_id for s in self._subscriptions}),
            "delivery_counts": dict(self._delivery_counts),
            "error_counts": dict(self._error_counts),
        }
