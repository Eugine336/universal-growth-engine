"""
UGIE Core — Event Processing Module

Responsibilities:
- Define the universal event schema
- Validate incoming events
- Classify and enrich events
- Route events to downstream consumers
- Maintain an event bus for internal pub/sub
"""

from .schema import Event, EventType
from .validator import EventValidator
from .enricher import EventEnricher
from .router import EventRouter
from .bus import EventBus

__all__ = [
    "Event",
    "EventType",
    "EventValidator",
    "EventEnricher",
    "EventRouter",
    "EventBus",
]
