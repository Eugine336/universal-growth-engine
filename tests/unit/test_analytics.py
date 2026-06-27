"""Unit tests for the Analytics Engine."""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone

from core.analytics.engine import AnalyticsEngine
from core.analytics.schema import (
    ChurnBreakdown,
    EngagementBreakdown,
    FunnelMetrics,
    PlatformDashboard,
    PredictionSummary,
    RFMBreakdown,
)
from core.audience.engine import AudienceEngine
from core.behavior.repository import BehaviorRepository
from core.behavior.schema import BehavioralProfile
from core.experimentation.engine import ExperimentationEngine
from core.experimentation.schema import Experiment, ExperimentVariant
from core.identity.cross_platform import CrossPlatformManager
from core.identity.graph import IdentityGraph
from core.prediction.engine import PredictionEngine
from core.referral.engine import ReferralEngine


@pytest.fixture()
def components():
    behavior_repo = BehaviorRepository()
    identity_graph = IdentityGraph()
    prediction_engine = PredictionEngine(behavior_repo)
    experimentation_engine = ExperimentationEngine()
    referral_engine = ReferralEngine()
    audience_engine = AudienceEngine(behavior_repo)
    cross_platform_manager = CrossPlatformManager(identity_graph, behavior_repo)
    engine = AnalyticsEngine(
        behavior_repo=behavior_repo,
        prediction_engine=prediction_engine,
        experimentation_engine=experimentation_engine,
        referral_engine=referral_engine,
        audience_engine=audience_engine,
        identity_graph=identity_graph,
        cross_platform_manager=cross_platform_manager,
    )
    return {
        "engine": engine,
        "behavior_repo": behavior_repo,
        "identity_graph": identity_graph,
        "prediction_engine": prediction_engine,
        "experimentation_engine": experimentation_engine,
        "referral_engine": referral_engine,
        "audience_engine": audience_engine,
        "cross_platform_manager": cross_platform_manager,
    }


def _make_profile(
    identity_id: str,
    app_id: str = "test_app",
    tier: str = "cold",
    rfm_segment: str = "new",
    churn_risk: str = "low",
    conversions: int = 0,
    registered: bool = False,
) -> BehavioralProfile:
    p = BehavioralProfile(identity_id=identity_id, application_id=app_id)
    p.engagement.tier = tier
    p.rfm.segment = rfm_segment
    p.rfm.total_conversions = conversions
    p.churn.risk_level = churn_risk
    if registered:
        p.event_counts["USER_REGISTERED"] = 1
    return p


class TestFunnelMetrics:

    def test_empty_platform(self, components):
        result = components["engine"].get_funnel_metrics("empty")
        assert result.total_identities == 0
        assert result.overall_conversion_rate == 0.0

    def test_full_funnel(self, components):
        repo = components["behavior_repo"]
        repo.save(_make_profile("u1", tier="power", rfm_segment="champions", conversions=5, registered=True))
        repo.save(_make_profile("u2", tier="active", rfm_segment="loyal", conversions=2, registered=True))
        repo.save(_make_profile("u3", tier="warming", rfm_segment="new", conversions=0, registered=True))
        repo.save(_make_profile("u4", tier="cold", rfm_segment="new", conversions=0, registered=False))

        result = components["engine"].get_funnel_metrics("test_app")
        assert result.total_identities == 4
        assert result.registered == 3
        assert result.activated == 3
        assert result.converted == 2
        assert result.retained == 2

    def test_division_by_zero(self, components):
        repo = components["behavior_repo"]
        repo.save(_make_profile("u1", tier="cold", conversions=0, registered=False))
        result = components["engine"].get_funnel_metrics("test_app")
        assert result.registration_to_activation_rate == 0.0
        assert result.activation_to_conversion_rate == 0.0
        assert result.conversion_to_retention_rate == 0.0

    def test_rates_calculated(self, components):
        repo = components["behavior_repo"]
        repo.save(_make_profile("u1", tier="power", conversions=3, registered=True))
        repo.save(_make_profile("u2", tier="warming", conversions=0, registered=True))
        result = components["engine"].get_funnel_metrics("test_app")
        assert result.registered == 2
        assert result.activated == 2
        assert result.converted == 1
        assert result.registration_to_activation_rate == 1.0


class TestEngagementBreakdown:

    def test_empty(self, components):
        result = components["engine"].get_engagement_breakdown("empty")
        assert result.total == 0

    def test_counts(self, components):
        repo = components["behavior_repo"]
        repo.save(_make_profile("u1", tier="power"))
        repo.save(_make_profile("u2", tier="active"))
        repo.save(_make_profile("u3", tier="active"))
        repo.save(_make_profile("u4", tier="warming"))
        repo.save(_make_profile("u5", tier="cold"))

        result = components["engine"].get_engagement_breakdown("test_app")
        assert result.power == 1
        assert result.active == 2
        assert result.warming == 1
        assert result.cold == 1
        assert result.total == 5


class TestRFMBreakdown:

    def test_empty(self, components):
        result = components["engine"].get_rfm_breakdown("empty")
        assert result.total == 0

    def test_segments(self, components):
        repo = components["behavior_repo"]
        repo.save(_make_profile("u1", rfm_segment="champions"))
        repo.save(_make_profile("u2", rfm_segment="loyal"))
        repo.save(_make_profile("u3", rfm_segment="at_risk"))
        repo.save(_make_profile("u4", rfm_segment="new"))
        repo.save(_make_profile("u5", rfm_segment="new"))

        result = components["engine"].get_rfm_breakdown("test_app")
        assert result.champions == 1
        assert result.loyal == 1
        assert result.at_risk == 1
        assert result.new == 2
        assert result.total == 5


class TestChurnBreakdown:

    def test_empty(self, components):
        result = components["engine"].get_churn_breakdown("empty")
        assert result.total == 0

    def test_risk_levels(self, components):
        repo = components["behavior_repo"]
        repo.save(_make_profile("u1", churn_risk="low"))
        repo.save(_make_profile("u2", churn_risk="medium"))
        repo.save(_make_profile("u3", churn_risk="high"))
        repo.save(_make_profile("u4", churn_risk="critical"))

        result = components["engine"].get_churn_breakdown("test_app")
        assert result.low == 1
        assert result.medium == 1
        assert result.high == 1
        assert result.critical == 1
        assert result.total == 4


class TestPredictionSummary:

    def test_empty(self, components):
        result = components["engine"].get_prediction_summary("empty")
        assert result == []

    def test_aggregates_scores(self, components):
        repo = components["behavior_repo"]
        repo.save(_make_profile("u1", tier="power", conversions=5, churn_risk="low"))
        repo.save(_make_profile("u2", tier="cold", conversions=0, churn_risk="high"))

        result = components["engine"].get_prediction_summary("test_app")
        assert len(result) > 0
        churn_summary = next(
            (s for s in result if s.prediction_type == "churn"), None
        )
        assert churn_summary is not None
        assert churn_summary.total_predictions == 2
        assert 0.0 <= churn_summary.avg_score <= 1.0


class TestExperimentSummary:

    def test_empty(self, components):
        result = components["engine"].get_experiment_summary("test_app")
        assert result.total_experiments == 0

    def test_with_experiments(self, components):
        exp_engine = components["experimentation_engine"]
        exp = Experiment(
            application_id="test_app",
            name="Test Exp",
            target_policy_id="policy_1",
            variants=[
                ExperimentVariant(id="v1", name="Control", weight=0.5),
                ExperimentVariant(id="v2", name="Treatment", weight=0.5),
            ],
        )
        exp_engine.register(exp)
        exp_engine.start(exp.id)

        result = components["engine"].get_experiment_summary("test_app")
        assert result.total_experiments == 1
        assert result.running == 1
        assert len(result.experiments) == 1
        assert result.experiments[0]["name"] == "Test Exp"

    def test_status_counts(self, components):
        exp_engine = components["experimentation_engine"]
        for i, status_action in enumerate(["start", None, "complete"]):
            exp = Experiment(
                application_id="test_app",
                name=f"Exp {i}",
                target_policy_id=f"p{i}",
                variants=[
                    ExperimentVariant(id=f"v{i}", name="A", weight=1.0),
                ],
            )
            exp_engine.register(exp)
            if status_action == "start":
                exp_engine.start(exp.id)
            elif status_action == "complete":
                exp_engine.start(exp.id)
                exp_engine.complete(exp.id)

        result = components["engine"].get_experiment_summary("test_app")
        assert result.total_experiments == 3
        assert result.running == 1
        assert result.completed == 1
        assert result.draft == 1


class TestReferralSummary:

    def test_empty(self, components):
        result = components["engine"].get_referral_summary("test_app")
        assert result.total_programs == 0

    def test_with_program(self, components):
        ref_engine = components["referral_engine"]
        ref_engine.create_program(platform_id="test_app", name="Growth")

        result = components["engine"].get_referral_summary("test_app")
        assert result.total_programs == 1


class TestAudienceSummary:

    def test_empty(self, components):
        result = components["engine"].get_audience_summary("test_app")
        assert result.total_audiences == 0

    def test_with_audiences(self, components):
        from core.audience.schema import AudienceDefinition

        aud_engine = components["audience_engine"]
        aud_engine.create_audience(
            "test_app",
            AudienceDefinition(name="Power Users"),
        )
        aud_engine.create_audience(
            "test_app",
            AudienceDefinition(name="At Risk"),
        )

        result = components["engine"].get_audience_summary("test_app")
        assert result.total_audiences == 2


class TestGrowthMetrics:

    def test_empty(self, components):
        result = components["engine"].get_growth_metrics("empty")
        assert result["total_users"] == 0
        assert result["dau_mau_ratio"] == 0.0

    def test_with_users(self, components):
        repo = components["behavior_repo"]
        repo.save(_make_profile("u1", tier="power"))
        repo.save(_make_profile("u2", tier="active"))
        repo.save(_make_profile("u3", tier="cold"))

        result = components["engine"].get_growth_metrics("test_app")
        assert result["total_users"] == 3
        assert result["active_users"] == 2
        assert result["new_users_7d"] == 3

    def test_old_users_excluded_from_new(self, components):
        repo = components["behavior_repo"]
        old_profile = _make_profile("u1", tier="power")
        old_profile.created_at = datetime.now(timezone.utc) - timedelta(days=60)
        repo.save(old_profile)

        result = components["engine"].get_growth_metrics("test_app")
        assert result["total_users"] == 1
        assert result["new_users_7d"] == 0
        assert result["new_users_30d"] == 0


class TestDashboard:

    def test_full_dashboard(self, components):
        repo = components["behavior_repo"]
        repo.save(_make_profile("u1", tier="power", conversions=3, registered=True))
        repo.save(_make_profile("u2", tier="cold", churn_risk="high", registered=True))

        result = components["engine"].get_dashboard("test_app")
        assert isinstance(result, PlatformDashboard)
        assert result.platform_id == "test_app"
        assert result.funnel.total_identities == 2
        assert result.engagement.total == 2
        assert result.rfm.total == 2
        assert result.churn.total == 2
        assert isinstance(result.identity_stats, dict)
        assert isinstance(result.cross_platform, dict)
