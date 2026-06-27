"""Tests for the experimentation engine."""

import pytest
from collections import Counter

from core.experimentation.schema import (
    Experiment,
    ExperimentAssignment,
    ExperimentStatus,
    ExperimentVariant,
)
from core.experimentation.engine import ExperimentationEngine
from core.decision.schema import Decision, ActionType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_experiment(
    experiment_id="exp_001",
    policy_id="policy_churn",
    app_id="ucmc",
    status=ExperimentStatus.RUNNING,
    weights=(0.5, 0.5),
    overrides_b=None,
    target_rfm=None,
    target_tiers=None,
):
    variants = [
        ExperimentVariant(id="control", name="Control", weight=weights[0]),
        ExperimentVariant(
            id="variant_a",
            name="Variant A",
            weight=weights[1],
            policy_overrides=overrides_b or {},
        ),
    ]
    return Experiment(
        id=experiment_id,
        application_id=app_id,
        name="Test Experiment",
        target_policy_id=policy_id,
        variants=variants,
        status=status,
        target_rfm_segments=target_rfm or [],
        target_engagement_tiers=target_tiers or [],
    )


def _make_decision(policy_id="policy_churn", app_id="ucmc"):
    return Decision(
        identity_id="identity_001",
        application_id=app_id,
        action_type=ActionType.SEND_EMAIL,
        priority=50,
        payload={"template": "original"},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDeterministicAssignment:

    def test_same_identity_always_gets_same_variant(self):
        engine = ExperimentationEngine()
        exp = _make_experiment()
        engine.register(exp)

        a1 = engine.assign(exp, "identity_001")
        a2 = engine.assign(exp, "identity_001")
        assert a1.variant_id == a2.variant_id
        assert a1.experiment_id == a2.experiment_id

    def test_different_identities_can_get_different_variants(self):
        engine = ExperimentationEngine()
        exp = _make_experiment()
        engine.register(exp)

        variants_seen = set()
        for i in range(100):
            a = engine.assign(exp, f"identity_{i}")
            variants_seen.add(a.variant_id)
        assert len(variants_seen) == 2

    def test_sticky_assignment_returns_same_object(self):
        engine = ExperimentationEngine()
        exp = _make_experiment()
        engine.register(exp)

        a1 = engine.assign(exp, "id_sticky")
        a2 = engine.assign(exp, "id_sticky")
        assert a1 is a2


class TestWeightDistribution:

    def test_50_50_split_is_approximately_even(self):
        engine = ExperimentationEngine()
        exp = _make_experiment(weights=(0.5, 0.5))
        engine.register(exp)

        counts = Counter()
        for i in range(1000):
            a = engine.assign(exp, f"user_{i}")
            counts[a.variant_id] += 1

        assert 350 < counts["control"] < 650
        assert 350 < counts["variant_a"] < 650

    def test_90_10_split_skews_correctly(self):
        engine = ExperimentationEngine()
        exp = _make_experiment(weights=(0.9, 0.1))
        engine.register(exp)

        counts = Counter()
        for i in range(1000):
            a = engine.assign(exp, f"user_{i}")
            counts[a.variant_id] += 1

        assert counts["control"] > 800
        assert counts["variant_a"] < 200


class TestVariantOverrides:

    def test_apply_variant_sets_experiment_fields(self):
        engine = ExperimentationEngine()
        exp = _make_experiment()
        engine.register(exp)

        decision = _make_decision()
        assignment = engine.assign(exp, "identity_001")
        engine.apply_variant(decision, assignment, exp)

        assert decision.experiment_id == exp.id
        assert decision.variant_id == assignment.variant_id

    def test_apply_variant_overrides_payload(self):
        engine = ExperimentationEngine()
        exp = _make_experiment(
            overrides_b={"payload.template": "new_email_v2"},
        )
        engine.register(exp)

        decision = _make_decision()
        decision.payload = {"template": "original"}

        assignment = ExperimentAssignment(
            experiment_id=exp.id,
            variant_id="variant_a",
            identity_id="identity_001",
        )
        engine.apply_variant(decision, assignment, exp)

        assert decision.payload["template"] == "new_email_v2"

    def test_apply_variant_overrides_priority(self):
        engine = ExperimentationEngine()
        exp = _make_experiment(overrides_b={"priority": 90})
        engine.register(exp)

        decision = _make_decision()
        assignment = ExperimentAssignment(
            experiment_id=exp.id,
            variant_id="variant_a",
            identity_id="identity_001",
        )
        engine.apply_variant(decision, assignment, exp)

        assert decision.priority == 90


class TestExperimentLifecycle:

    def test_draft_to_running(self):
        engine = ExperimentationEngine()
        exp = _make_experiment(status=ExperimentStatus.DRAFT)
        engine.register(exp)

        result = engine.start(exp.id)
        assert result.status == ExperimentStatus.RUNNING
        assert result.starts_at is not None

    def test_running_to_paused(self):
        engine = ExperimentationEngine()
        exp = _make_experiment(status=ExperimentStatus.RUNNING)
        engine.register(exp)

        result = engine.pause(exp.id)
        assert result.status == ExperimentStatus.PAUSED

    def test_paused_to_running(self):
        engine = ExperimentationEngine()
        exp = _make_experiment(status=ExperimentStatus.PAUSED)
        engine.register(exp)

        result = engine.start(exp.id)
        assert result.status == ExperimentStatus.RUNNING

    def test_running_to_completed(self):
        engine = ExperimentationEngine()
        exp = _make_experiment(status=ExperimentStatus.RUNNING)
        engine.register(exp)

        result = engine.complete(exp.id)
        assert result.status == ExperimentStatus.COMPLETED
        assert result.ends_at is not None

    def test_completed_cannot_restart(self):
        engine = ExperimentationEngine()
        exp = _make_experiment(status=ExperimentStatus.COMPLETED)
        engine.register(exp)

        result = engine.start(exp.id)
        assert result.status == ExperimentStatus.COMPLETED


class TestPolicyLookup:

    def test_get_active_for_policy_returns_running(self):
        engine = ExperimentationEngine()
        exp = _make_experiment(status=ExperimentStatus.RUNNING)
        engine.register(exp)

        found = engine.get_active_for_policy("policy_churn", "ucmc")
        assert found is not None
        assert found.id == exp.id

    def test_get_active_for_policy_ignores_draft(self):
        engine = ExperimentationEngine()
        exp = _make_experiment(status=ExperimentStatus.DRAFT)
        engine.register(exp)

        found = engine.get_active_for_policy("policy_churn", "ucmc")
        assert found is None

    def test_get_active_for_policy_wrong_policy(self):
        engine = ExperimentationEngine()
        exp = _make_experiment(status=ExperimentStatus.RUNNING)
        engine.register(exp)

        found = engine.get_active_for_policy("other_policy", "ucmc")
        assert found is None


class TestTargeting:

    def test_no_targeting_matches_everything(self):
        engine = ExperimentationEngine()
        exp = _make_experiment()
        assert engine.matches_targeting(exp, "champions", "power")

    def test_rfm_targeting_matches(self):
        engine = ExperimentationEngine()
        exp = _make_experiment(target_rfm=["champions", "loyal"])
        assert engine.matches_targeting(exp, "champions", "power")
        assert not engine.matches_targeting(exp, "at_risk", "power")

    def test_tier_targeting_matches(self):
        engine = ExperimentationEngine()
        exp = _make_experiment(target_tiers=["power"])
        assert engine.matches_targeting(exp, "champions", "power")
        assert not engine.matches_targeting(exp, "champions", "cold")


class TestConversionTracking:

    def test_record_conversion_increments(self):
        engine = ExperimentationEngine()
        exp = _make_experiment()
        engine.register(exp)

        engine.assign(exp, "identity_001")
        ok = engine.record_conversion(exp.id, "identity_001")
        assert ok is True

        results = engine.get_results(exp.id)
        variant_id = engine.assign(exp, "identity_001").variant_id
        assert results["variants"][variant_id]["conversions"] == 1

    def test_record_conversion_fails_for_unassigned(self):
        engine = ExperimentationEngine()
        exp = _make_experiment()
        engine.register(exp)

        ok = engine.record_conversion(exp.id, "unknown_identity")
        assert ok is False


class TestResults:

    def test_get_results_structure(self):
        engine = ExperimentationEngine()
        exp = _make_experiment()
        engine.register(exp)

        for i in range(10):
            engine.assign(exp, f"user_{i}")

        results = engine.get_results(exp.id)
        assert results["experiment_id"] == exp.id
        assert results["status"] == "running"
        assert "control" in results["variants"] or "variant_a" in results["variants"]

    def test_conversion_rate_calculation(self):
        engine = ExperimentationEngine()
        exp = _make_experiment()
        engine.register(exp)

        engine.assign(exp, "user_0")
        engine.assign(exp, "user_1")
        engine.record_conversion(exp.id, "user_0")

        results = engine.get_results(exp.id)
        for variant_data in results["variants"].values():
            if variant_data["assignments"] > 0 and variant_data["conversions"] > 0:
                assert variant_data["conversion_rate"] > 0


class TestStats:

    def test_stats_structure(self):
        engine = ExperimentationEngine()
        exp = _make_experiment()
        engine.register(exp)
        engine.assign(exp, "user_0")

        stats = engine.stats()
        assert stats["total_experiments"] == 1
        assert stats["total_assignments"] == 1
        assert "running" in stats["by_status"]


class TestListExperiments:

    def test_list_by_application(self):
        engine = ExperimentationEngine()
        engine.register(_make_experiment(experiment_id="e1", app_id="ucmc"))
        engine.register(_make_experiment(experiment_id="e2", app_id="trading"))

        assert len(engine.list_experiments(application_id="ucmc")) == 1

    def test_list_by_status(self):
        engine = ExperimentationEngine()
        engine.register(_make_experiment(experiment_id="e1", status=ExperimentStatus.RUNNING))
        engine.register(_make_experiment(experiment_id="e2", status=ExperimentStatus.DRAFT))

        assert len(engine.list_experiments(status=ExperimentStatus.RUNNING)) == 1
