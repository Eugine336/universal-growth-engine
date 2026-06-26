"""
Unit Tests — core/behavior

Tests cover:
- BehavioralProfile schema
- BehaviorBuilder event-by-event profile updates
- BehaviorRepository CRUD and queries
- BehaviorAnalyzer RFM, churn detection, segmentation
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest
from datetime import datetime, timezone, timedelta

from core.events.schema import Event, EventType, EventContext
from core.behavior.schema import BehavioralProfile, IntentSignal
from core.behavior.builder import BehaviorBuilder
from core.behavior.repository import BehaviorRepository
from core.behavior.analyzer import BehaviorAnalyzer


# ===========================================================================
# Fixtures
# ===========================================================================

def make_event(type: EventType, properties: dict = None, **kwargs) -> Event:
    return Event(
        application_id="ucmc",
        type=type,
        actor_id="user_001",
        actor_type="Buyer",
        properties=properties or {},
        **kwargs
    )

def make_profile(identity_id="identity_001", application_id="ucmc") -> BehavioralProfile:
    return BehavioralProfile(
        identity_id=identity_id,
        application_id=application_id,
    )

def make_repo() -> BehaviorRepository:
    return BehaviorRepository()

def make_builder() -> BehaviorBuilder:
    return BehaviorBuilder()


# ===========================================================================
# BehavioralProfile Schema Tests
# ===========================================================================

class TestBehavioralProfileSchema:

    def test_profile_created_with_defaults(self):
        p = make_profile()
        assert p.identity_id == "identity_001"
        assert p.engagement.total_events == 0
        assert p.rfm.total_conversions == 0
        assert p.churn.risk_level == "low"

    def test_increment_event(self):
        p = make_profile()
        p.increment_event("USER_REGISTERED")
        p.increment_event("USER_REGISTERED")
        assert p.get_event_count("USER_REGISTERED") == 2
        assert p.get_event_count("PAYMENT_COMPLETED") == 0

    def test_set_and_get_intent_signal(self):
        p = make_profile()
        signal = IntentSignal(
            signal_type="purchase_intent",
            strength=0.7,
            triggering_events=["ITEM_VIEWED"],
        )
        p.set_intent_signal(signal)
        fetched = p.get_intent_signal("purchase_intent")
        assert fetched is not None
        assert fetched.strength == 0.7

    def test_set_trait(self):
        p = make_profile()
        p.set_trait("country", "KE")
        assert p.traits["country"] == "KE"

    def test_touch_updates_timestamps(self):
        p = make_profile()
        assert p.last_event_at is None
        p.touch()
        assert p.last_event_at is not None


# ===========================================================================
# BehaviorBuilder Tests
# ===========================================================================

class TestBehaviorBuilder:

    def setup_method(self):
        self.builder = make_builder()

    def test_apply_increments_event_count(self):
        p = make_profile()
        event = make_event(EventType.SESSION_STARTED)
        self.builder.apply(event, p)
        assert p.get_event_count("SESSION_STARTED") == 1

    def test_session_started_increments_sessions(self):
        p = make_profile()
        self.builder.apply(make_event(EventType.SESSION_STARTED), p)
        assert p.engagement.total_sessions == 1

    def test_page_viewed_increments_page_views(self):
        p = make_profile()
        self.builder.apply(make_event(EventType.PAGE_VIEWED), p)
        assert p.engagement.total_page_views == 1

    def test_feature_used_recorded(self):
        p = make_profile()
        self.builder.apply(
            make_event(EventType.FEATURE_USED, {"feature_name": "dashboard"}),
            p
        )
        assert "dashboard" in p.engagement.unique_features_used
        assert p.engagement.total_feature_uses == 1

    def test_duplicate_feature_not_added_twice(self):
        p = make_profile()
        for _ in range(3):
            self.builder.apply(
                make_event(EventType.FEATURE_USED, {"feature_name": "chat"}),
                p
            )
        assert p.engagement.unique_features_used.count("chat") == 1

    def test_engagement_tier_cold_initially(self):
        p = make_profile()
        assert p.engagement.tier == "cold"

    def test_engagement_tier_warming_after_session(self):
        p = make_profile()
        self.builder.apply(make_event(EventType.SESSION_STARTED), p)
        assert p.engagement.tier == "warming"

    def test_category_interest_tracked(self):
        p = make_profile()
        self.builder.apply(
            make_event(EventType.ITEM_VIEWED, {"category": "design", "item_id": "item_001"}),
            p
        )
        assert p.interests.category_interests.get("design") == 1

    def test_search_term_recorded(self):
        p = make_profile()
        self.builder.apply(
            make_event(EventType.SEARCH_EXECUTED, {"query": "logo design"}),
            p
        )
        assert "logo design" in p.interests.search_terms

    def test_item_viewed_recorded(self):
        p = make_profile()
        self.builder.apply(
            make_event(EventType.ITEM_VIEWED, {"item_id": "item_abc"}),
            p
        )
        assert "item_abc" in p.interests.viewed_item_ids

    def test_item_saved_recorded(self):
        p = make_profile()
        self.builder.apply(
            make_event(EventType.ITEM_SAVED, {"item_id": "item_xyz"}),
            p
        )
        assert "item_xyz" in p.interests.saved_item_ids

    def test_payment_completed_increments_rfm(self):
        p = make_profile()
        self.builder.apply(
            make_event(EventType.PAYMENT_COMPLETED, {"amount": 150.0, "currency": "USD"}),
            p
        )
        assert p.rfm.total_conversions == 1
        assert p.rfm.total_monetary_value == 150.0

    def test_multiple_payments_accumulate(self):
        p = make_profile()
        for amount in [100.0, 200.0, 50.0]:
            self.builder.apply(
                make_event(EventType.PAYMENT_COMPLETED, {"amount": amount, "currency": "USD"}),
                p
            )
        assert p.rfm.total_conversions == 3
        assert p.rfm.total_monetary_value == 350.0
        assert round(p.rfm.avg_monetary_value, 2) == round(350.0 / 3, 2)

    def test_friction_event_increments_friction_count(self):
        p = make_profile()
        self.builder.apply(make_event(EventType.DISPUTE_OPENED, {"reason": "non-delivery"}), p)
        assert p.churn.has_friction_events is True
        assert p.churn.recent_friction_count == 1

    def test_subscription_cancelled_sets_flag(self):
        p = make_profile()
        self.builder.apply(make_event(EventType.SUBSCRIPTION_CANCELLED), p)
        assert p.churn.cancelled_subscription is True

    def test_reactivation_event_reduces_churn_risk(self):
        p = make_profile()
        # First create churn risk
        p.churn.risk_level = "medium"
        p.churn.risk_score = 0.4
        # Reactivate
        self.builder.apply(make_event(EventType.SESSION_STARTED), p)
        assert p.churn.risk_score < 0.4

    def test_purchase_intent_signal_grows(self):
        p = make_profile()
        for _ in range(3):
            self.builder.apply(
                make_event(EventType.ITEM_VIEWED, {"item_id": "x"}),
                p
            )
        signal = p.get_intent_signal("purchase_intent")
        assert signal is not None
        assert signal.strength > 0.3

    def test_purchase_intent_capped_at_1(self):
        p = make_profile()
        for _ in range(20):
            self.builder.apply(
                make_event(EventType.ITEM_VIEWED, {"item_id": "x"}),
                p
            )
        signal = p.get_intent_signal("purchase_intent")
        assert signal.strength <= 1.0

    def test_email_open_updates_open_rate(self):
        p = make_profile()
        self.builder.apply(make_event(EventType.EMAIL_SENT), p)
        self.builder.apply(make_event(EventType.EMAIL_OPENED), p)
        assert p.communication.email_open_rate > 0

    def test_email_unsubscribe_adds_to_blocked_channels(self):
        p = make_profile()
        self.builder.apply(make_event(EventType.EMAIL_UNSUBSCRIBED), p)
        assert "email" in p.communication.unsubscribed_channels

    def test_review_intent_after_payment(self):
        p = make_profile()
        self.builder.apply(
            make_event(EventType.PAYMENT_COMPLETED, {"amount": 50.0, "currency": "USD"}),
            p
        )
        signal = p.get_intent_signal("review_intent")
        assert signal is not None
        assert signal.strength == 0.7


# ===========================================================================
# BehaviorRepository Tests
# ===========================================================================

class TestBehaviorRepository:

    def setup_method(self):
        self.repo = make_repo()

    def test_get_or_create_creates_new_profile(self):
        p = self.repo.get_or_create("identity_001", "ucmc")
        assert p is not None
        assert p.identity_id == "identity_001"

    def test_get_or_create_returns_existing(self):
        p1 = self.repo.get_or_create("identity_001", "ucmc")
        p1.set_trait("test", True)
        self.repo.save(p1)
        p2 = self.repo.get_or_create("identity_001", "ucmc")
        assert p2.traits.get("test") is True

    def test_save_and_get(self):
        p = make_profile()
        self.repo.save(p)
        fetched = self.repo.get("identity_001", "ucmc")
        assert fetched is not None

    def test_delete(self):
        p = make_profile()
        self.repo.save(p)
        self.repo.delete("identity_001", "ucmc")
        assert self.repo.get("identity_001", "ucmc") is None

    def test_list_by_application(self):
        self.repo.get_or_create("identity_001", "ucmc")
        self.repo.get_or_create("identity_002", "ucmc")
        self.repo.get_or_create("identity_003", "trading")
        ucmc = self.repo.list_by_application("ucmc")
        assert len(ucmc) == 2

    def test_find_by_churn_risk(self):
        p = self.repo.get_or_create("identity_001", "ucmc")
        p.churn.risk_level = "high"
        self.repo.save(p)
        found = self.repo.find_by_churn_risk("ucmc", "high")
        assert len(found) == 1

    def test_find_by_rfm_segment(self):
        p = self.repo.get_or_create("identity_001", "ucmc")
        p.rfm.segment = "champions"
        self.repo.save(p)
        found = self.repo.find_by_rfm_segment("ucmc", "champions")
        assert len(found) == 1

    def test_find_by_engagement_tier(self):
        p = self.repo.get_or_create("identity_001", "ucmc")
        p.engagement.tier = "power"
        self.repo.save(p)
        found = self.repo.find_by_engagement_tier("ucmc", "power")
        assert len(found) == 1

    def test_find_with_intent(self):
        p = self.repo.get_or_create("identity_001", "ucmc")
        p.set_intent_signal(IntentSignal(
            signal_type="purchase_intent",
            strength=0.8,
        ))
        self.repo.save(p)
        found = self.repo.find_with_intent("ucmc", "purchase_intent", min_strength=0.5)
        assert len(found) == 1

    def test_stats(self):
        p = self.repo.get_or_create("identity_001", "ucmc")
        p.engagement.tier = "active"
        self.repo.save(p)
        stats = self.repo.stats("ucmc")
        assert stats["total_profiles"] == 1
        assert stats["engagement_tiers"].get("active") == 1


# ===========================================================================
# BehaviorAnalyzer Tests
# ===========================================================================

class TestBehaviorAnalyzer:

    def setup_method(self):
        self.repo = make_repo()
        self.builder = make_builder()
        self.analyzer = BehaviorAnalyzer(self.repo)

    def _make_active_profile(self, identity_id: str, sessions: int = 5, amount: float = 100.0):
        p = self.repo.get_or_create(identity_id, "ucmc")
        for _ in range(sessions):
            self.builder.apply(make_event(EventType.SESSION_STARTED), p)
        self.builder.apply(
            make_event(EventType.PAYMENT_COMPLETED, {"amount": amount, "currency": "USD"}),
            p
        )
        self.repo.save(p)
        return p

    def test_recompute_rfm_updates_scores(self):
        self._make_active_profile("identity_001", amount=500.0)
        self._make_active_profile("identity_002", amount=100.0)
        count = self.analyzer.recompute_rfm("ucmc")
        assert count == 2
        p1 = self.repo.get("identity_001", "ucmc")
        p2 = self.repo.get("identity_002", "ucmc")
        assert p1.rfm.monetary_score >= p2.rfm.monetary_score

    def test_detect_churn_windows_finds_inactive_users(self):
        p = self.repo.get_or_create("inactive_user", "ucmc")
        p.engagement.total_sessions = 5
        p.engagement.last_active_at = (
            datetime.now(timezone.utc) - timedelta(days=30)
        )
        self.repo.save(p)
        at_risk = self.analyzer.detect_churn_windows("ucmc", inactivity_threshold_days=14)
        assert len(at_risk) >= 1

    def test_detect_churn_ignores_never_active_users(self):
        p = self.repo.get_or_create("new_user", "ucmc")
        p.engagement.total_sessions = 0
        p.engagement.last_active_at = (
            datetime.now(timezone.utc) - timedelta(days=30)
        )
        self.repo.save(p)
        at_risk = self.analyzer.detect_churn_windows("ucmc", inactivity_threshold_days=14)
        assert len(at_risk) == 0

    def test_find_reengagement_candidates(self):
        p = self.repo.get_or_create("lapsed_user", "ucmc")
        p.engagement.total_sessions = 10
        p.engagement.last_active_at = (
            datetime.now(timezone.utc) - timedelta(days=20)
        )
        p.rfm.segment = "at_risk"
        self.repo.save(p)
        candidates = self.analyzer.find_reengagement_candidates("ucmc")
        assert len(candidates) >= 1

    def test_find_power_users(self):
        p = self._make_active_profile("power_user", sessions=10, amount=500.0)
        p.engagement.sessions_last_7d = 6
        p.rfm.total_conversions = 5
        p.churn.risk_level = "low"
        self.repo.save(p)
        power = self.analyzer.find_power_users("ucmc", min_sessions_7d=5, min_conversions=2)
        assert len(power) >= 1

    def test_analyze_application_returns_report(self):
        self._make_active_profile("user_001")
        self._make_active_profile("user_002")
        report = self.analyzer.analyze_application("ucmc")
        assert report["application_id"] == "ucmc"
        assert report["total_profiles"] == 2

    def test_analyze_empty_application(self):
        report = self.analyzer.analyze_application("empty_app")
        assert report["total_profiles"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
