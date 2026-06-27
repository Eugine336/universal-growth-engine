"""
Unit Tests — core/decision

Tests cover:
- Decision schema
- PolicyCondition evaluation
- Policy targeting and trigger matching
- PolicyRegistry registration and filtering
- PolicyEvaluator: condition matching, suppression, priority ranking
- DecisionEngine: full decide loop, history, batch
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest
from datetime import datetime, timezone, timedelta

from core.behavior.schema import BehavioralProfile, IntentSignal
from core.behavior.repository import BehaviorRepository
from core.prediction.engine import PredictionEngine
from core.prediction.schema import PredictionSet, PredictionType, Prediction

from core.decision.schema import (
    Decision, DecisionStatus, ActionType, DecisionContext, DecisionOutcome
)
from core.decision.policy import (
    Policy, PolicyCondition, PolicyAction, PolicyRegistry
)
from core.decision.evaluator import PolicyEvaluator
from core.decision.engine import DecisionEngine


# ===========================================================================
# Fixtures
# ===========================================================================

def make_profile(
    identity_id="identity_001",
    application_id="ucmc",
    engagement_tier="active",
    rfm_segment="loyal",
    churn_score=0.2,
    days_inactive=2.0,
    churn_risk="low",
) -> BehavioralProfile:
    p = BehavioralProfile(identity_id=identity_id, application_id=application_id)
    p.engagement.tier = engagement_tier
    p.rfm.segment = rfm_segment
    p.churn.days_inactive = days_inactive
    p.churn.risk_level = churn_risk
    p.churn.risk_score = churn_score
    return p


def make_prediction_set(
    identity_id="identity_001",
    churn=0.2,
    fraud=0.1,
    conversion=0.4,
    upsell=0.3,
    referral=0.2,
    ltv=0.5,
) -> PredictionSet:
    ps = PredictionSet(identity_id=identity_id, application_id="ucmc")
    scores = {
        PredictionType.CHURN: churn,
        PredictionType.FRAUD: fraud,
        PredictionType.CONVERSION: conversion,
        PredictionType.UPSELL: upsell,
        PredictionType.REFERRAL: referral,
        PredictionType.LTV: ltv,
    }
    for ptype, score in scores.items():
        ps.set(Prediction(
            identity_id=identity_id,
            application_id="ucmc",
            type=ptype,
            score=score,
        ))
    return ps


def make_policy(
    application_id="ucmc",
    name="test_policy",
    conditions=None,
    action_type=ActionType.SEND_EMAIL,
    priority=50,
    cooldown_hours=0.0,
    trigger_events=None,
    target_rfm_segments=None,
    target_engagement_tiers=None,
) -> Policy:
    return Policy(
        application_id=application_id,
        name=name,
        conditions=conditions or [],
        trigger_events=trigger_events or [],
        target_rfm_segments=target_rfm_segments or [],
        target_engagement_tiers=target_engagement_tiers or [],
        action=PolicyAction(
            action_type=action_type,
            priority=priority,
            payload_template={"template": "test"},
            valid_hours=24.0,
        ),
        cooldown_hours=cooldown_hours,
    )


def make_engine_stack(
    profile: BehavioralProfile = None,
) -> tuple:
    repo = BehaviorRepository()
    if profile:
        repo.save(profile)
    pred_engine = PredictionEngine(repo)
    registry = PolicyRegistry()
    # Clear seeded global policies for test isolation
    registry._policies.clear()
    engine = DecisionEngine(
        behavior_repo=repo,
        prediction_engine=pred_engine,
        policy_registry=registry,
    )
    return engine, repo, registry


# ===========================================================================
# Decision Schema Tests
# ===========================================================================

class TestDecisionSchema:

    def test_decision_created_with_defaults(self):
        d = Decision(
            identity_id="id_001",
            application_id="ucmc",
            action_type=ActionType.SEND_EMAIL,
        )
        assert d.status == DecisionStatus.PENDING
        assert d.id is not None

    def test_is_executable_when_pending(self):
        d = Decision(
            identity_id="id_001",
            application_id="ucmc",
            action_type=ActionType.SEND_EMAIL,
        )
        assert d.is_executable() is True

    def test_not_executable_when_expired(self):
        d = Decision(
            identity_id="id_001",
            application_id="ucmc",
            action_type=ActionType.SEND_EMAIL,
            valid_until=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        assert d.is_executable() is False

    def test_not_executable_before_execute_after(self):
        d = Decision(
            identity_id="id_001",
            application_id="ucmc",
            action_type=ActionType.SEND_EMAIL,
            execute_after=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        assert d.is_executable() is False

    def test_mark_executed(self):
        d = Decision(
            identity_id="id_001",
            application_id="ucmc",
            action_type=ActionType.SEND_EMAIL,
        )
        outcome = DecisionOutcome(success=True)
        d.mark_executed(outcome)
        assert d.status == DecisionStatus.EXECUTED
        assert d.outcome.success is True

    def test_mark_suppressed(self):
        d = Decision(
            identity_id="id_001",
            application_id="ucmc",
            action_type=ActionType.SEND_EMAIL,
        )
        d.mark_suppressed("cooldown active")
        assert d.status == DecisionStatus.SUPPRESSED

    def test_is_expired(self):
        d = Decision(
            identity_id="id_001",
            application_id="ucmc",
            action_type=ActionType.SEND_EMAIL,
            valid_until=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        assert d.is_expired() is True


# ===========================================================================
# PolicyCondition Tests
# ===========================================================================

class TestPolicyCondition:

    def test_eq(self):
        c = PolicyCondition(field="tier", operator="eq", value="active")
        assert c.evaluate({"tier": "active"}) is True
        assert c.evaluate({"tier": "cold"}) is False

    def test_gte(self):
        c = PolicyCondition(field="churn_score", operator="gte", value=0.6)
        assert c.evaluate({"churn_score": 0.7}) is True
        assert c.evaluate({"churn_score": 0.5}) is False

    def test_gt(self):
        c = PolicyCondition(field="sessions", operator="gt", value=5)
        assert c.evaluate({"sessions": 6}) is True
        assert c.evaluate({"sessions": 5}) is False

    def test_lt(self):
        c = PolicyCondition(field="fraud_score", operator="lt", value=0.3)
        assert c.evaluate({"fraud_score": 0.2}) is True
        assert c.evaluate({"fraud_score": 0.4}) is False

    def test_lte(self):
        c = PolicyCondition(field="days_inactive", operator="lte", value=7.0)
        assert c.evaluate({"days_inactive": 7.0}) is True
        assert c.evaluate({"days_inactive": 8.0}) is False

    def test_in(self):
        c = PolicyCondition(field="segment", operator="in", value=["champions", "loyal"])
        assert c.evaluate({"segment": "champions"}) is True
        assert c.evaluate({"segment": "new"}) is False

    def test_not_in(self):
        c = PolicyCondition(field="tier", operator="not_in", value=["cold", "warming"])
        assert c.evaluate({"tier": "active"}) is True
        assert c.evaluate({"tier": "cold"}) is False

    def test_exists(self):
        c = PolicyCondition(field="email", operator="exists", value=None)
        assert c.evaluate({"email": "x@y.com"}) is True
        assert c.evaluate({}) is False

    def test_missing_field_returns_false(self):
        c = PolicyCondition(field="nonexistent", operator="eq", value="x")
        assert c.evaluate({}) is False

    def test_neq(self):
        c = PolicyCondition(field="status", operator="neq", value="suspended")
        assert c.evaluate({"status": "active"}) is True
        assert c.evaluate({"status": "suspended"}) is False


# ===========================================================================
# Policy Tests
# ===========================================================================

class TestPolicy:

    def test_policy_is_active_by_default(self):
        p = make_policy()
        assert p.is_active() is True

    def test_disabled_policy_not_active(self):
        p = make_policy()
        p.enabled = False
        assert p.is_active() is False

    def test_policy_not_active_before_start(self):
        p = make_policy()
        p.starts_at = datetime.now(timezone.utc) + timedelta(days=1)
        assert p.is_active() is False

    def test_policy_not_active_after_end(self):
        p = make_policy()
        p.ends_at = datetime.now(timezone.utc) - timedelta(days=1)
        assert p.is_active() is False

    def test_matches_trigger_no_filter(self):
        p = make_policy(trigger_events=[])
        assert p.matches_trigger("ANY_EVENT") is True

    def test_matches_trigger_with_filter(self):
        p = make_policy(trigger_events=["PAYMENT_COMPLETED"])
        assert p.matches_trigger("PAYMENT_COMPLETED") is True
        assert p.matches_trigger("SESSION_STARTED") is False

    def test_matches_target_no_filters(self):
        p = make_policy()
        assert p.matches_target({"rfm_segment": "new", "engagement_tier": "cold"}) is True

    def test_matches_target_rfm_filter(self):
        p = make_policy(target_rfm_segments=["champions", "loyal"])
        assert p.matches_target({"rfm_segment": "champions"}) is True
        assert p.matches_target({"rfm_segment": "new"}) is False

    def test_matches_target_engagement_filter(self):
        p = make_policy(target_engagement_tiers=["power"])
        assert p.matches_target({"engagement_tier": "power"}) is True
        assert p.matches_target({"engagement_tier": "cold"}) is False

    def test_condition_and_logic(self):
        p = make_policy(conditions=[
            PolicyCondition(field="churn_score", operator="gte", value=0.5),
            PolicyCondition(field="days_inactive", operator="gte", value=14.0),
        ])
        assert p.evaluate_conditions({
            "churn_score": 0.7, "days_inactive": 20.0
        }) is True
        assert p.evaluate_conditions({
            "churn_score": 0.7, "days_inactive": 5.0
        }) is False

    def test_condition_or_logic(self):
        p = make_policy(conditions=[
            PolicyCondition(field="churn_score", operator="gte", value=0.8),
            PolicyCondition(field="fraud_score", operator="gte", value=0.8),
        ])
        p.condition_logic = "OR"
        assert p.evaluate_conditions({"churn_score": 0.9, "fraud_score": 0.1}) is True
        assert p.evaluate_conditions({"churn_score": 0.1, "fraud_score": 0.9}) is True
        assert p.evaluate_conditions({"churn_score": 0.1, "fraud_score": 0.1}) is False

    def test_no_conditions_always_matches(self):
        p = make_policy(conditions=[])
        assert p.evaluate_conditions({}) is True


# ===========================================================================
# Policy Registry Tests
# ===========================================================================

class TestPolicyRegistry:

    def setup_method(self):
        self.registry = PolicyRegistry()
        self.registry._policies.clear()   # isolate from seeded globals

    def test_register_and_get(self):
        p = make_policy()
        self.registry.register(p)
        assert self.registry.get(p.id) is not None

    def test_get_active_returns_only_active(self):
        p1 = make_policy(application_id="ucmc", name="active_policy")
        p2 = make_policy(application_id="ucmc", name="disabled_policy")
        p2.enabled = False
        self.registry.register(p1)
        self.registry.register(p2)
        active = self.registry.get_active("ucmc")
        names = [p.name for p in active]
        assert "active_policy" in names
        assert "disabled_policy" not in names

    def test_get_active_filters_by_application(self):
        self.registry.register(make_policy(application_id="ucmc", name="ucmc_policy"))
        self.registry.register(make_policy(application_id="trading", name="trading_policy"))
        active = self.registry.get_active("ucmc")
        assert all(p.name != "trading_policy" for p in active)

    def test_wildcard_application_matches_all(self):
        p = make_policy(application_id="*", name="global_policy")
        self.registry.register(p)
        assert any(p.name == "global_policy" for p in self.registry.get_active("ucmc"))
        assert any(p.name == "global_policy" for p in self.registry.get_active("trading"))

    def test_trigger_filter(self):
        p = make_policy(application_id="ucmc", trigger_events=["PAYMENT_COMPLETED"])
        self.registry.register(p)
        matched = self.registry.get_active("ucmc", trigger_event="PAYMENT_COMPLETED")
        not_matched = self.registry.get_active("ucmc", trigger_event="SESSION_STARTED")
        assert p in matched
        assert p not in not_matched

    def test_disable_and_enable(self):
        p = make_policy(application_id="ucmc")
        self.registry.register(p)
        self.registry.disable(p.id)
        assert p not in self.registry.get_active("ucmc")
        self.registry.enable(p.id)
        assert p in self.registry.get_active("ucmc")

    def test_count(self):
        self.registry.register(make_policy(application_id="ucmc"))
        self.registry.register(make_policy(application_id="ucmc"))
        assert self.registry.count("ucmc") == 2


# ===========================================================================
# PolicyEvaluator Tests
# ===========================================================================

class TestPolicyEvaluator:

    def setup_method(self):
        self.registry = PolicyRegistry()
        self.registry._policies.clear()
        self.evaluator = PolicyEvaluator(self.registry)

    def test_matching_policy_produces_decision(self):
        policy = make_policy(
            application_id="ucmc",
            conditions=[
                PolicyCondition(field="churn_score", operator="gte", value=0.1)
            ],
            action_type=ActionType.TRIGGER_REENGAGEMENT,
            priority=70,
        )
        self.registry.register(policy)
        profile = make_profile(churn_score=0.5)
        ps = make_prediction_set(churn=0.5)
        decisions = self.evaluator.evaluate(profile, ps)
        assert len(decisions) == 1
        assert decisions[0].action_type == ActionType.TRIGGER_REENGAGEMENT

    def test_non_matching_conditions_produces_no_decision(self):
        policy = make_policy(
            application_id="ucmc",
            conditions=[
                PolicyCondition(field="churn_score", operator="gte", value=0.9)
            ],
        )
        self.registry.register(policy)
        profile = make_profile(churn_score=0.1)
        ps = make_prediction_set(churn=0.1)
        decisions = self.evaluator.evaluate(profile, ps)
        assert len(decisions) == 0

    def test_higher_priority_policy_wins(self):
        low = make_policy(application_id="ucmc", name="low", priority=30,
                          action_type=ActionType.SEND_EMAIL)
        high = make_policy(application_id="ucmc", name="high", priority=90,
                           action_type=ActionType.FLAG_FOR_REVIEW)
        self.registry.register(low)
        self.registry.register(high)
        profile = make_profile()
        ps = make_prediction_set()
        decisions = self.evaluator.evaluate(profile, ps)
        assert decisions[0].priority == 90

    def test_cooldown_suppresses_repeated_policy(self):
        policy = make_policy(
            application_id="ucmc",
            cooldown_hours=24.0,
            action_type=ActionType.SEND_EMAIL,
        )
        self.registry.register(policy)
        profile = make_profile()
        ps = make_prediction_set()

        # First evaluation — should produce a decision
        d1 = self.evaluator.evaluate(profile, ps)
        assert len(d1) == 1

        # Second evaluation with that decision in history — should be suppressed
        d2 = self.evaluator.evaluate(profile, ps, decision_history=d1)
        assert len(d2) == 0

    def test_channel_block_suppresses(self):
        policy = make_policy(
            application_id="ucmc",
            action_type=ActionType.SEND_EMAIL,
        )
        policy.action.channel = "email"
        self.registry.register(policy)
        profile = make_profile()
        profile.communication.unsubscribed_channels = ["email"]
        ps = make_prediction_set()
        decisions = self.evaluator.evaluate(profile, ps)
        assert len(decisions) == 0

    def test_daily_comm_cap_suppresses(self):
        policy = make_policy(
            application_id="ucmc",
            action_type=ActionType.SEND_EMAIL,
        )
        self.registry.register(policy)
        profile = make_profile()
        ps = make_prediction_set()

        # Fill up the daily cap with existing decisions
        from core.decision.schema import Decision
        history = []
        for _ in range(3):
            d = Decision(
                identity_id=profile.identity_id,
                application_id="ucmc",
                action_type=ActionType.SEND_EMAIL,
            )
            history.append(d)

        decisions = self.evaluator.evaluate(profile, ps, decision_history=history)
        assert len(decisions) == 0

    def test_rfm_targeting_filter(self):
        policy = make_policy(
            application_id="ucmc",
            target_rfm_segments=["champions"],
            action_type=ActionType.SHOW_UPSELL,
        )
        self.registry.register(policy)

        # Non-champion — should not match
        profile = make_profile(rfm_segment="new")
        ps = make_prediction_set()
        decisions = self.evaluator.evaluate(profile, ps)
        assert len(decisions) == 0

        # Champion — should match
        profile2 = make_profile(rfm_segment="champions")
        decisions2 = self.evaluator.evaluate(profile2, ps)
        assert len(decisions2) == 1

    def test_best_decision_returns_top_only(self):
        for priority, action in [(30, ActionType.SEND_EMAIL),
                                  (80, ActionType.FLAG_FOR_REVIEW)]:
            self.registry.register(make_policy(
                application_id="ucmc", priority=priority, action_type=action
            ))
        profile = make_profile()
        ps = make_prediction_set()
        best = self.evaluator.best_decision(profile, ps)
        assert best is not None
        assert best.priority == 80


# ===========================================================================
# DecisionEngine Tests
# ===========================================================================

class TestDecisionEngine:

    def setup_method(self):
        self.profile = make_profile()
        self.engine, self.repo, self.registry = make_engine_stack(self.profile)

    def _add_policy(self, **kwargs) -> Policy:
        p = make_policy(**kwargs)
        self.engine.register_policy(p)
        return p

    def test_decide_returns_empty_when_no_profile(self):
        decisions = self.engine.decide("ghost", "ucmc")
        assert decisions == []

    def test_decide_returns_empty_when_no_policies(self):
        decisions = self.engine.decide("identity_001", "ucmc")
        assert decisions == []

    def test_decide_returns_decision_when_policy_matches(self):
        self._add_policy(
            application_id="ucmc",
            action_type=ActionType.TRIGGER_REENGAGEMENT,
            priority=70,
        )
        decisions = self.engine.decide("identity_001", "ucmc")
        assert len(decisions) == 1
        assert decisions[0].action_type == ActionType.TRIGGER_REENGAGEMENT

    def test_decide_best_returns_single_decision(self):
        self._add_policy(application_id="ucmc", action_type=ActionType.SEND_EMAIL)
        best = self.engine.decide_best("identity_001", "ucmc")
        assert best is not None
        assert isinstance(best, Decision)

    def test_decide_all_returns_all_decisions(self):
        for action in [ActionType.SEND_EMAIL, ActionType.SHOW_UPSELL, ActionType.REQUEST_REVIEW]:
            self._add_policy(application_id="ucmc", action_type=action)
        decisions = self.engine.decide("identity_001", "ucmc", return_all=True)
        assert len(decisions) == 3

    def test_decision_stored_in_history(self):
        self._add_policy(application_id="ucmc", action_type=ActionType.SEND_EMAIL)
        self.engine.decide("identity_001", "ucmc")
        history = self.engine.get_history("identity_001")
        assert len(history) == 1

    def test_mark_executed(self):
        self._add_policy(application_id="ucmc", action_type=ActionType.SEND_EMAIL)
        decisions = self.engine.decide("identity_001", "ucmc")
        d = decisions[0]
        result = self.engine.mark_executed(d.id, "identity_001", success=True)
        assert result is not None
        assert result.status == DecisionStatus.EXECUTED

    def test_decide_batch(self):
        for i in range(3):
            p = make_profile(identity_id=f"identity_00{i}")
            self.repo.save(p)
        self._add_policy(application_id="ucmc", action_type=ActionType.SEND_EMAIL)
        results = self.engine.decide_batch("ucmc")
        assert len(results) >= 3

    def test_disable_policy_stops_decisions(self):
        p = self._add_policy(application_id="ucmc", action_type=ActionType.SEND_EMAIL)
        self.engine.disable_policy(p.id)
        decisions = self.engine.decide("identity_001", "ucmc")
        assert len(decisions) == 0

    def test_enable_policy_resumes_decisions(self):
        p = self._add_policy(application_id="ucmc", action_type=ActionType.SEND_EMAIL)
        self.engine.disable_policy(p.id)
        self.engine.enable_policy(p.id)
        decisions = self.engine.decide("identity_001", "ucmc")
        assert len(decisions) == 1

    def test_trigger_event_filter(self):
        p = self._add_policy(
            application_id="ucmc",
            trigger_events=["PAYMENT_COMPLETED"],
            action_type=ActionType.REQUEST_REVIEW,
        )
        # Wrong trigger — should not match
        d1 = self.engine.decide(
            "identity_001", "ucmc",
            trigger_event_type="SESSION_STARTED"
        )
        assert len(d1) == 0

        # Correct trigger — should match
        d2 = self.engine.decide(
            "identity_001", "ucmc",
            trigger_event_type="PAYMENT_COMPLETED"
        )
        assert len(d2) == 1

    def test_stats(self):
        self._add_policy(application_id="ucmc", action_type=ActionType.SEND_EMAIL)
        self.engine.decide("identity_001", "ucmc")
        stats = self.engine.stats()
        assert stats["total_decided"] >= 1
        assert stats["registered_policies"] >= 1

    def test_decision_context_populated(self):
        self._add_policy(application_id="ucmc", action_type=ActionType.SEND_EMAIL)
        decisions = self.engine.decide("identity_001", "ucmc")
        assert decisions[0].context.engagement_tier is not None
        assert decisions[0].context.policy_name is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
