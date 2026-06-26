"""
Unit Tests — core/events

Tests cover:
- Event schema validation
- EventValidator rules
- EventEnricher enrichment
- EventRouter subscription and delivery
- EventBus full pipeline
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest
from datetime import datetime, timezone, timedelta

from core.events.schema import Event, EventType, EventSource, EventContext
from core.events.validator import EventValidator, ApplicationEventPolicy, ValidationResult
from core.events.enricher import EventEnricher
from core.events.router import EventRouter
from core.events.bus import EventBus


# ===========================================================================
# Fixtures
# ===========================================================================

def make_event(**kwargs) -> Event:
    defaults = dict(
        application_id="test_app",
        type=EventType.USER_REGISTERED,
        actor_id="user_001",
        actor_type="User",
    )
    defaults.update(kwargs)
    return Event(**defaults)


def make_bus() -> EventBus:
    bus = EventBus()
    bus.register_application(ApplicationEventPolicy(application_id="test_app"))
    return bus


# ===========================================================================
# Schema tests
# ===========================================================================

class TestEventSchema:

    def test_event_creates_with_defaults(self):
        event = make_event()
        assert event.id is not None
        assert event.processed is False
        assert event.received_at is None

    def test_effective_type_standard(self):
        event = make_event(type=EventType.PAYMENT_COMPLETED)
        assert event.effective_type() == "PAYMENT_COMPLETED"

    def test_effective_type_custom(self):
        event = make_event(type=EventType.CUSTOM, custom_type="ESCROW_RELEASED")
        assert event.effective_type() == "CUSTOM:ESCROW_RELEASED"

    def test_custom_type_required_when_custom(self):
        with pytest.raises(Exception):
            make_event(type=EventType.CUSTOM, custom_type=None)

    def test_mark_received(self):
        event = make_event()
        event.mark_received()
        assert event.received_at is not None

    def test_mark_processed(self):
        event = make_event()
        event.mark_processed()
        assert event.processed is True

    def test_add_error(self):
        event = make_event()
        event.add_error("something went wrong")
        assert "something went wrong" in event.processing_errors


# ===========================================================================
# Validator tests
# ===========================================================================

class TestEventValidator:

    def setup_method(self):
        self.validator = EventValidator()
        self.policy = ApplicationEventPolicy(application_id="test_app")
        self.validator.register_policy(self.policy)

    def test_valid_event_passes(self):
        event = make_event()
        result = self.validator.validate(event)
        assert result.valid is True

    def test_missing_application_id_fails(self):
        event = make_event(application_id="")
        result = self.validator.validate(event)
        assert result.valid is False
        assert any("application_id" in e for e in result.errors)

    def test_unknown_application_warns(self):
        event = make_event(application_id="unknown_app")
        result = self.validator.validate(event)
        assert result.valid is True
        assert len(result.warnings) > 0

    def test_missing_required_property_fails(self):
        event = make_event(
            type=EventType.PAYMENT_COMPLETED,
            properties={}
        )
        result = self.validator.validate(event)
        assert result.valid is False
        assert any("amount" in e for e in result.errors)

    def test_event_with_required_properties_passes(self):
        event = make_event(
            type=EventType.PAYMENT_COMPLETED,
            properties={"amount": 100.0, "currency": "USD"}
        )
        result = self.validator.validate(event)
        assert result.valid is True

    def test_future_timestamp_fails(self):
        event = make_event(
            timestamp=datetime.now(timezone.utc) + timedelta(hours=48)
        )
        result = self.validator.validate(event)
        assert result.valid is False

    def test_old_timestamp_warns(self):
        event = make_event(
            timestamp=datetime.now(timezone.utc) - timedelta(days=10)
        )
        result = self.validator.validate(event)
        assert result.valid is True
        assert any("7 days" in w for w in result.warnings)

    def test_blocked_event_type_fails(self):
        policy = ApplicationEventPolicy(
            application_id="restricted_app",
            blocked_events={"LOGIN_FAILED"}
        )
        self.validator.register_policy(policy)
        event = make_event(
            application_id="restricted_app",
            type=EventType.LOGIN_FAILED
        )
        result = self.validator.validate(event)
        assert result.valid is False

    def test_custom_event_without_custom_type_fails(self):
        # Pydantic raises ValidationError at construction time
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            Event(
                application_id="test_app",
                type=EventType.CUSTOM,
                custom_type=None,
                actor_id="user_001",
            )


# ===========================================================================
# Enricher tests
# ===========================================================================

class TestEventEnricher:

    def setup_method(self):
        self.enricher = EventEnricher()

    def test_stamps_received_at(self):
        event = make_event()
        self.enricher.enrich(event)
        assert "_ugie" in event.properties
        assert "received_at" in event.properties["_ugie"]

    def test_sets_category(self):
        event = make_event(type=EventType.PAYMENT_COMPLETED)
        self.enricher.enrich(event)
        assert event.properties["_ugie"]["category"] == "transaction"

    def test_sets_conversion_flag(self):
        event = make_event(type=EventType.PAYMENT_COMPLETED)
        self.enricher.enrich(event)
        assert event.properties["_ugie"]["is_conversion"] is True

    def test_sets_friction_flag(self):
        event = make_event(type=EventType.DISPUTE_OPENED,
                           properties={"reason": "non-delivery"})
        self.enricher.enrich(event)
        assert event.properties["_ugie"]["is_friction"] is True

    def test_normalizes_utm(self):
        event = make_event(
            context=EventContext(
                utm_source="  Google  ",
                utm_medium="CPC",
                utm_campaign="Summer_Sale",
            )
        )
        self.enricher.enrich(event)
        utm = event.properties["_ugie"]["utm"]
        assert utm["source"] == "google"
        assert utm["medium"] == "cpc"
        assert utm["campaign"] == "summer_sale"

    def test_no_utm_if_none_present(self):
        event = make_event()
        self.enricher.enrich(event)
        assert "utm" not in event.properties["_ugie"]

    def test_has_session_false_when_no_session(self):
        event = make_event()
        self.enricher.enrich(event)
        assert event.properties["_ugie"]["has_session"] is False

    def test_has_session_true_when_session_present(self):
        event = make_event(context=EventContext(session_id="sess_abc"))
        self.enricher.enrich(event)
        assert event.properties["_ugie"]["has_session"] is True


# ===========================================================================
# Router tests
# ===========================================================================

class TestEventRouter:

    def setup_method(self):
        self.router = EventRouter()
        self.received: list = []

    def _handler(self, event: Event):
        self.received.append(event)

    def test_event_delivered_to_matching_subscriber(self):
        self.router.subscribe(
            consumer_id="test",
            handler=self._handler,
            event_types={"USER_REGISTERED"}
        )
        event = make_event(type=EventType.USER_REGISTERED)
        delivered = self.router.route(event)
        assert delivered == 1
        assert len(self.received) == 1

    def test_event_not_delivered_to_non_matching_subscriber(self):
        self.router.subscribe(
            consumer_id="test",
            handler=self._handler,
            event_types={"PAYMENT_COMPLETED"}
        )
        event = make_event(type=EventType.USER_REGISTERED)
        delivered = self.router.route(event)
        assert delivered == 0

    def test_wildcard_subscriber_receives_all(self):
        self.router.subscribe(consumer_id="audit", handler=self._handler)
        for t in [EventType.USER_REGISTERED, EventType.PAYMENT_COMPLETED, EventType.SESSION_STARTED]:
            self.router.route(make_event(type=t))
        assert len(self.received) == 3

    def test_unsubscribe_stops_delivery(self):
        self.router.subscribe(consumer_id="temp", handler=self._handler)
        self.router.route(make_event())
        self.router.unsubscribe("temp")
        self.router.route(make_event())
        assert len(self.received) == 1

    def test_faulty_handler_does_not_crash_bus(self):
        def bad_handler(event):
            raise RuntimeError("consumer failure")

        self.router.subscribe(consumer_id="bad", handler=bad_handler)
        self.router.subscribe(consumer_id="good", handler=self._handler)
        event = make_event()
        delivered = self.router.route(event)
        assert delivered == 1  # good handler still received it
        assert len(self.received) == 1

    def test_application_filter(self):
        self.router.subscribe(
            consumer_id="ucmc_only",
            handler=self._handler,
            application_ids={"ucmc"}
        )
        self.router.route(make_event(application_id="trading"))
        assert len(self.received) == 0
        self.router.route(make_event(application_id="ucmc"))
        assert len(self.received) == 1


# ===========================================================================
# EventBus integration tests
# ===========================================================================

class TestEventBus:

    def setup_method(self):
        self.bus = make_bus()
        self.received: list = []

    def _handler(self, event: Event):
        self.received.append(event)

    def test_valid_event_processes_successfully(self):
        event = make_event()
        result = self.bus.submit(event)
        assert result.success is True
        assert event.processed is True
        assert event.received_at is not None

    def test_invalid_event_returns_failure(self):
        event = make_event(application_id="")
        result = self.bus.submit(event)
        assert result.success is False
        assert len(result.errors) > 0

    def test_event_delivered_to_subscriber(self):
        self.bus.subscribe(
            consumer_id="test",
            handler=self._handler,
            event_types={"USER_REGISTERED"}
        )
        self.bus.submit(make_event(type=EventType.USER_REGISTERED))
        assert len(self.received) == 1

    def test_batch_submit(self):
        self.bus.subscribe(consumer_id="all", handler=self._handler)
        events = [make_event() for _ in range(5)]
        results = self.bus.submit_batch(events)
        assert len(results) == 5
        assert all(r.success for r in results)
        assert len(self.received) == 5

    def test_stats_track_counts(self):
        self.bus.submit(make_event())
        self.bus.submit(make_event(application_id=""))
        stats = self.bus.stats()
        assert stats["total_received"] == 2
        assert stats["total_processed"] == 1
        assert stats["total_failed"] == 1

    def test_recent_events_filtered_by_app(self):
        self.bus.register_application(ApplicationEventPolicy(application_id="other_app"))
        self.bus.submit(make_event(application_id="test_app"))
        self.bus.submit(make_event(application_id="other_app"))
        recent = self.bus.recent_events(application_id="test_app")
        assert len(recent) == 1
        assert recent[0].application_id == "test_app"

    def test_enrichment_applied_before_routing(self):
        enriched_events = []
        def check_enrichment(event):
            enriched_events.append(event)

        self.bus.subscribe(consumer_id="checker", handler=check_enrichment)
        self.bus.submit(make_event(type=EventType.PAYMENT_COMPLETED,
                                   properties={"amount": 50, "currency": "USD"}))
        assert "_ugie" in enriched_events[0].properties
        assert enriched_events[0].properties["_ugie"]["is_conversion"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
