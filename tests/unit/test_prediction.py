"""
Unit Tests — core/prediction

Tests cover:
- Prediction schema
- Each individual predictor
- PredictionEngine orchestration, caching, batch
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest
from datetime import datetime, timezone, timedelta

from core.behavior.schema import BehavioralProfile, IntentSignal
from core.behavior.builder import BehaviorBuilder
from core.behavior.repository import BehaviorRepository
from core.events.schema import Event, EventType
from core.prediction.schema import Prediction, PredictionType, PredictionSet
from core.prediction.engine import PredictionEngine
from core.prediction.predictors.churn import ChurnPredictor
from core.prediction.predictors.conversion import ConversionPredictor
from core.prediction.predictors.ltv import LTVPredictor
from core.prediction.predictors.upsell import UpsellPredictor
from core.prediction.predictors.referral import ReferralPredictor
from core.prediction.predictors.fraud import FraudPredictor


# ===========================================================================
# Fixtures
# ===========================================================================

def make_event(etype: EventType, props: dict = None) -> Event:
    return Event(
        application_id="ucmc",
        type=etype,
        actor_id="user_001",
        actor_type="Buyer",
        properties=props or {},
    )

def make_profile(identity_id="identity_001") -> BehavioralProfile:
    return BehavioralProfile(identity_id=identity_id, application_id="ucmc")

def build_profile(*events) -> BehavioralProfile:
    """Build a profile by applying a sequence of events."""
    profile = make_profile()
    builder = BehaviorBuilder()
    for event in events:
        builder.apply(event, profile)
    return profile

def make_engine() -> tuple:
    repo = BehaviorRepository()
    engine = PredictionEngine(repo)
    return engine, repo


# ===========================================================================
# Prediction Schema Tests
# ===========================================================================

class TestPredictionSchema:

    def test_prediction_created(self):
        p = Prediction(
            identity_id="id_001",
            application_id="ucmc",
            type=PredictionType.CHURN,
            score=0.72,
        )
        assert p.score == 0.72
        assert p.type == PredictionType.CHURN

    def test_is_valid_when_no_expiry(self):
        p = Prediction(
            identity_id="id_001",
            application_id="ucmc",
            type=PredictionType.CHURN,
            score=0.5,
        )
        assert p.is_valid() is True

    def test_is_not_valid_when_expired(self):
        p = Prediction(
            identity_id="id_001",
            application_id="ucmc",
            type=PredictionType.CHURN,
            score=0.5,
            valid_until=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        assert p.is_valid() is False

    def test_is_high_risk(self):
        p = Prediction(
            identity_id="id_001",
            application_id="ucmc",
            type=PredictionType.CHURN,
            score=0.80,
        )
        assert p.is_high_risk() is True
        assert p.is_high_risk(threshold=0.9) is False

    def test_prediction_set_get_and_set(self):
        ps = PredictionSet(identity_id="id_001", application_id="ucmc")
        pred = Prediction(
            identity_id="id_001",
            application_id="ucmc",
            type=PredictionType.FRAUD,
            score=0.3,
        )
        ps.set(pred)
        assert ps.get(PredictionType.FRAUD) is not None
        assert ps.get(PredictionType.CHURN) is None

    def test_prediction_set_all_scores(self):
        ps = PredictionSet(identity_id="id_001", application_id="ucmc")
        for ptype, score in [(PredictionType.CHURN, 0.5), (PredictionType.FRAUD, 0.2)]:
            ps.set(Prediction(
                identity_id="id_001",
                application_id="ucmc",
                type=ptype,
                score=score,
            ))
        scores = ps.all_scores()
        assert "churn" in scores
        assert "fraud" in scores

    def test_prediction_set_highest_risk(self):
        ps = PredictionSet(identity_id="id_001", application_id="ucmc")
        ps.set(Prediction(identity_id="id_001", application_id="ucmc",
                          type=PredictionType.CHURN, score=0.8))
        ps.set(Prediction(identity_id="id_001", application_id="ucmc",
                          type=PredictionType.FRAUD, score=0.3))
        highest = ps.highest_risk()
        assert highest.type == PredictionType.CHURN


# ===========================================================================
# Churn Predictor Tests
# ===========================================================================

class TestChurnPredictor:

    def setup_method(self):
        self.predictor = ChurnPredictor()

    def test_new_user_low_churn(self):
        profile = make_profile()
        result = self.predictor.predict(profile)
        assert result.score < 0.4
        assert result.type == PredictionType.CHURN

    def test_inactive_user_high_churn(self):
        profile = make_profile()
        profile.churn.days_inactive = 90.0
        profile.engagement.tier = "cold"
        result = self.predictor.predict(profile)
        assert result.score >= 0.35

    def test_cancelled_subscription_raises_score(self):
        profile = make_profile()
        profile.churn.cancelled_subscription = True
        result = self.predictor.predict(profile)
        assert result.score >= 0.25

    def test_friction_events_raise_score(self):
        profile = make_profile()
        profile.churn.has_friction_events = True
        profile.churn.recent_friction_count = 3
        result = self.predictor.predict(profile)
        assert result.score > 0.1

    def test_power_user_lower_churn(self):
        profile = make_profile()
        profile.engagement.tier = "power"
        profile.engagement.sessions_last_7d = 8
        result = self.predictor.predict(profile)
        assert result.score < 0.3

    def test_prediction_includes_explanation(self):
        profile = make_profile()
        profile.churn.days_inactive = 60
        result = self.predictor.predict(profile)
        assert len(result.explanation) > 0

    def test_score_bounded_0_to_1(self):
        profile = make_profile()
        profile.churn.days_inactive = 999
        profile.churn.cancelled_subscription = True
        profile.churn.recent_friction_count = 20
        result = self.predictor.predict(profile)
        assert 0.0 <= result.score <= 1.0


# ===========================================================================
# Conversion Predictor Tests
# ===========================================================================

class TestConversionPredictor:

    def setup_method(self):
        self.predictor = ConversionPredictor()

    def test_cold_user_low_conversion(self):
        profile = make_profile()
        result = self.predictor.predict(profile)
        assert result.score < 0.3

    def test_high_intent_raises_conversion(self):
        profile = make_profile()
        profile.set_intent_signal(IntentSignal(
            signal_type="purchase_intent",
            strength=0.9,
        ))
        result = self.predictor.predict(profile)
        assert result.score > 0.2

    def test_saved_items_raise_score(self):
        profile = make_profile()
        profile.interests.saved_item_ids = ["a", "b", "c", "d"]
        result = self.predictor.predict(profile)
        assert result.score > 0.0

    def test_recent_activity_raises_score(self):
        profile = make_profile()
        profile.churn.days_inactive = 0.0
        result = self.predictor.predict(profile)
        assert result.score > 0.1

    def test_past_conversions_positive_signal(self):
        profile = make_profile()
        profile.rfm.total_conversions = 5
        result = self.predictor.predict(profile)
        assert result.score > 0.0

    def test_score_bounded(self):
        profile = make_profile()
        profile.set_intent_signal(IntentSignal(signal_type="purchase_intent", strength=1.0))
        profile.interests.saved_item_ids = [f"item_{i}" for i in range(20)]
        profile.rfm.total_conversions = 50
        profile.engagement.tier = "power"
        result = self.predictor.predict(profile)
        assert 0.0 <= result.score <= 1.0


# ===========================================================================
# LTV Predictor Tests
# ===========================================================================

class TestLTVPredictor:

    def setup_method(self):
        self.predictor = LTVPredictor()

    def test_no_conversions_no_value(self):
        profile = make_profile()
        result = self.predictor.predict(profile)
        assert result.factors.get("ltv_raw", 0) == 0.0
        assert result.label == "no_value"

    def test_high_value_user_labelled_correctly(self):
        profile = make_profile()
        profile.rfm.total_conversions = 20
        profile.rfm.total_monetary_value = 50000.0
        profile.rfm.avg_monetary_value = 2500.0
        profile.rfm.segment = "champions"
        profile.engagement.tier = "power"
        profile.churn.risk_level = "low"
        result = self.predictor.predict(profile)
        assert result.label in ("high_value", "enterprise")

    def test_churn_risk_reduces_ltv(self):
        low_risk = make_profile("low_risk")
        low_risk.rfm.avg_monetary_value = 100.0
        low_risk.rfm.total_conversions = 5
        low_risk.churn.risk_level = "low"

        high_risk = make_profile("high_risk")
        high_risk.rfm.avg_monetary_value = 100.0
        high_risk.rfm.total_conversions = 5
        high_risk.churn.risk_level = "critical"

        r_low = self.predictor.predict(low_risk)
        r_high = self.predictor.predict(high_risk)
        assert r_low.factors.get("ltv_raw", 0) >= r_high.factors.get("ltv_raw", 0)

    def test_score_bounded(self):
        profile = make_profile()
        profile.rfm.avg_monetary_value = 99999.0
        profile.rfm.total_conversions = 1000
        result = self.predictor.predict(profile)
        assert 0.0 <= result.score <= 1.0


# ===========================================================================
# Upsell Predictor Tests
# ===========================================================================

class TestUpsellPredictor:

    def setup_method(self):
        self.predictor = UpsellPredictor()

    def test_cold_user_low_upsell(self):
        result = self.predictor.predict(make_profile())
        assert result.score < 0.3

    def test_upsell_signal_raises_score(self):
        profile = make_profile()
        profile.set_intent_signal(IntentSignal(
            signal_type="upsell_ready", strength=0.8
        ))
        result = self.predictor.predict(profile)
        assert result.score > 0.2

    def test_champion_segment_positive(self):
        profile = make_profile()
        profile.rfm.segment = "champions"
        profile.engagement.tier = "power"
        result = self.predictor.predict(profile)
        assert result.score > 0.2

    def test_at_risk_segment_negative(self):
        profile = make_profile()
        profile.rfm.segment = "at_risk"
        profile.churn.risk_level = "high"
        result = self.predictor.predict(profile)
        # Should be lower than a champion
        champion = make_profile("champ")
        champion.rfm.segment = "champions"
        r_champ = self.predictor.predict(champion)
        assert result.score <= r_champ.score


# ===========================================================================
# Referral Predictor Tests
# ===========================================================================

class TestReferralPredictor:

    def setup_method(self):
        self.predictor = ReferralPredictor()

    def test_no_signals_low_referral(self):
        result = self.predictor.predict(make_profile())
        assert result.score < 0.3

    def test_referral_signal_raises_score(self):
        profile = make_profile()
        profile.set_intent_signal(IntentSignal(
            signal_type="referral_intent", strength=0.8
        ))
        result = self.predictor.predict(profile)
        assert result.score > 0.2

    def test_sharing_behavior_positive(self):
        profile = make_profile()
        profile.interests.shared_item_ids = ["a", "b", "c"]
        result = self.predictor.predict(profile)
        assert result.score > 0.0

    def test_score_bounded(self):
        profile = make_profile()
        profile.set_intent_signal(IntentSignal(signal_type="referral_intent", strength=1.0))
        profile.interests.shared_item_ids = [f"item_{i}" for i in range(10)]
        profile.rfm.segment = "champions"
        result = self.predictor.predict(profile)
        assert 0.0 <= result.score <= 1.0


# ===========================================================================
# Fraud Predictor Tests
# ===========================================================================

class TestFraudPredictor:

    def setup_method(self):
        self.predictor = FraudPredictor()

    def test_clean_user_low_fraud(self):
        result = self.predictor.predict(make_profile())
        assert result.score < 0.2

    def test_high_login_failures_raise_score(self):
        profile = make_profile()
        profile.event_counts["LOGIN_FAILED"] = 10
        profile.event_counts["LOGIN_SUCCESS"] = 1
        result = self.predictor.predict(profile)
        assert result.score > 0.1

    def test_high_dispute_rate_raises_score(self):
        profile = make_profile()
        profile.event_counts["DISPUTE_OPENED"] = 5
        profile.rfm.total_conversions = 5
        result = self.predictor.predict(profile)
        assert result.score > 0.1

    def test_rapid_transactions_new_account(self):
        profile = make_profile()
        profile.engagement.total_sessions = 1
        profile.rfm.total_conversions = 5
        result = self.predictor.predict(profile)
        assert result.factors.get("rapid_transaction", 0) > 0

    def test_high_session_velocity_suspicious(self):
        profile = make_profile()
        profile.engagement.sessions_last_7d = 60
        result = self.predictor.predict(profile)
        assert result.factors.get("session_velocity", 0) > 0

    def test_score_bounded(self):
        profile = make_profile()
        profile.event_counts["LOGIN_FAILED"] = 100
        profile.event_counts["DISPUTE_OPENED"] = 50
        profile.event_counts["REFUND_INITIATED"] = 30
        result = self.predictor.predict(profile)
        assert 0.0 <= result.score <= 1.0


# ===========================================================================
# Prediction Engine Tests
# ===========================================================================

class TestPredictionEngine:

    def setup_method(self):
        self.engine, self.repo = make_engine()

    def _save_profile(self, identity_id="identity_001") -> BehavioralProfile:
        profile = BehavioralProfile(
            identity_id=identity_id,
            application_id="ucmc",
        )
        self.repo.save(profile)
        return profile

    def test_predict_returns_none_for_missing_profile(self):
        result = self.engine.predict("ghost", "ucmc")
        assert result is None

    def test_predict_returns_prediction_set(self):
        self._save_profile()
        result = self.engine.predict("identity_001", "ucmc")
        assert result is not None
        assert isinstance(result, PredictionSet)

    def test_all_predictors_run_by_default(self):
        self._save_profile()
        result = self.engine.predict("identity_001", "ucmc")
        assert len(result.predictions) == len(list(PredictionType))

    def test_specific_prediction_types(self):
        self._save_profile()
        result = self.engine.predict(
            "identity_001", "ucmc",
            prediction_types=[PredictionType.CHURN, PredictionType.FRAUD]
        )
        assert PredictionType.CHURN.value in result.predictions
        assert PredictionType.FRAUD.value in result.predictions
        assert PredictionType.LTV.value not in result.predictions

    def test_cache_hit_on_second_call(self):
        self._save_profile()
        r1 = self.engine.predict("identity_001", "ucmc")
        r2 = self.engine.predict("identity_001", "ucmc")
        assert r1.id == r2.id

    def test_force_refresh_bypasses_cache(self):
        self._save_profile()
        r1 = self.engine.predict("identity_001", "ucmc")
        r2 = self.engine.predict("identity_001", "ucmc", force_refresh=True)
        assert r1.id != r2.id

    def test_predict_one(self):
        self._save_profile()
        result = self.engine.predict_one("identity_001", "ucmc", PredictionType.CHURN)
        assert result is not None
        assert result.type == PredictionType.CHURN

    def test_predict_batch(self):
        for i in range(3):
            self._save_profile(f"identity_00{i}")
        results = self.engine.predict_batch("ucmc")
        assert len(results) == 3

    def test_stats(self):
        stats = self.engine.stats()
        assert "registered_predictors" in stats
        assert len(stats["registered_predictors"]) == len(list(PredictionType))

    def test_invalidate_cache(self):
        self._save_profile()
        self.engine.predict("identity_001", "ucmc")
        self.engine.invalidate_cache("identity_001", "ucmc")
        r2 = self.engine.predict("identity_001", "ucmc")
        # New PredictionSet created after invalidation
        assert r2 is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
