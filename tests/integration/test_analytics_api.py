"""Integration tests for Analytics and Admin API endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.rest.app import create_app, pipeline
from core.behavior.schema import BehavioralProfile
from core.experimentation.schema import Experiment, ExperimentVariant


@pytest.fixture()
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    if pipeline.behavior_repo:
        pipeline.behavior_repo._profiles.clear()
    if pipeline.audience_engine:
        pipeline.audience_engine._audiences.clear()
    if pipeline.experimentation_engine:
        pipeline.experimentation_engine._experiments.clear()
        pipeline.experimentation_engine._assignments.clear()
    if pipeline.referral_engine:
        pipeline.referral_engine._programs.clear()
        pipeline.referral_engine._platform_programs.clear()
        pipeline.referral_engine._codes.clear()
        pipeline.referral_engine._code_lookup.clear()
        pipeline.referral_engine._referrals.clear()
    if pipeline.platform_registry:
        pipeline.platform_registry._platforms.clear()
        pipeline.platform_registry._slug_index.clear()
        pipeline.platform_registry._key_index.clear()
    if pipeline.prediction_engine:
        pipeline.prediction_engine.clear_cache()


def _seed_profiles():
    repo = pipeline.behavior_repo
    p1 = BehavioralProfile(identity_id="u1", application_id="default")
    p1.engagement.tier = "power"
    p1.rfm.segment = "champions"
    p1.rfm.total_conversions = 10
    p1.churn.risk_level = "low"
    p1.event_counts["USER_REGISTERED"] = 1
    repo.save(p1)

    p2 = BehavioralProfile(identity_id="u2", application_id="default")
    p2.engagement.tier = "active"
    p2.rfm.segment = "loyal"
    p2.rfm.total_conversions = 3
    p2.churn.risk_level = "medium"
    p2.event_counts["USER_REGISTERED"] = 1
    repo.save(p2)

    p3 = BehavioralProfile(identity_id="u3", application_id="default")
    p3.engagement.tier = "cold"
    p3.rfm.segment = "at_risk"
    p3.rfm.total_conversions = 0
    p3.churn.risk_level = "high"
    repo.save(p3)


class TestDashboardEndpoint:

    def test_empty_dashboard(self, client):
        resp = client.get("/api/v1/analytics/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert data["platform_id"] == "default"
        assert data["funnel"]["total_identities"] == 0

    def test_populated_dashboard(self, client):
        _seed_profiles()
        resp = client.get("/api/v1/analytics/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert data["funnel"]["total_identities"] == 3
        assert data["engagement"]["total"] == 3
        assert data["rfm"]["total"] == 3
        assert data["churn"]["total"] == 3

    def test_dashboard_with_platform_id(self, client):
        _seed_profiles()
        resp = client.get("/api/v1/analytics/dashboard?platform_id=default")
        assert resp.status_code == 200
        assert resp.json()["funnel"]["total_identities"] == 3


class TestFunnelEndpoint:

    def test_funnel(self, client):
        _seed_profiles()
        resp = client.get("/api/v1/analytics/funnel")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_identities"] == 3
        assert data["registered"] == 2
        assert data["activated"] == 2
        assert data["converted"] == 2
        assert data["retained"] == 2


class TestEngagementEndpoint:

    def test_engagement(self, client):
        _seed_profiles()
        resp = client.get("/api/v1/analytics/engagement")
        assert resp.status_code == 200
        data = resp.json()
        assert data["power"] == 1
        assert data["active"] == 1
        assert data["cold"] == 1
        assert data["total"] == 3


class TestRFMEndpoint:

    def test_rfm(self, client):
        _seed_profiles()
        resp = client.get("/api/v1/analytics/rfm")
        assert resp.status_code == 200
        data = resp.json()
        assert data["champions"] == 1
        assert data["loyal"] == 1
        assert data["at_risk"] == 1


class TestChurnEndpoint:

    def test_churn(self, client):
        _seed_profiles()
        resp = client.get("/api/v1/analytics/churn")
        assert resp.status_code == 200
        data = resp.json()
        assert data["low"] == 1
        assert data["medium"] == 1
        assert data["high"] == 1
        assert data["total"] == 3


class TestPredictionsEndpoint:

    def test_predictions(self, client):
        _seed_profiles()
        resp = client.get("/api/v1/analytics/predictions")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0
        for summary in data:
            assert "prediction_type" in summary
            assert "total_predictions" in summary
            assert "avg_score" in summary

    def test_predictions_empty(self, client):
        resp = client.get("/api/v1/analytics/predictions?platform_id=empty")
        assert resp.status_code == 200
        assert resp.json() == []


class TestExperimentsEndpoint:

    def test_experiments_empty(self, client):
        resp = client.get("/api/v1/analytics/experiments")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_experiments"] == 0

    def test_experiments_with_data(self, client):
        exp = Experiment(
            application_id="default",
            name="Homepage CTA",
            target_policy_id="cta_policy",
            variants=[
                ExperimentVariant(id="v1", name="Blue", weight=0.5),
                ExperimentVariant(id="v2", name="Green", weight=0.5),
            ],
        )
        pipeline.experimentation_engine.register(exp)
        pipeline.experimentation_engine.start(exp.id)

        resp = client.get("/api/v1/analytics/experiments?platform_id=default")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_experiments"] == 1
        assert data["running"] == 1
        assert len(data["experiments"]) == 1
        assert data["experiments"][0]["name"] == "Homepage CTA"


class TestReferralsEndpoint:

    def test_referrals_empty(self, client):
        resp = client.get("/api/v1/analytics/referrals")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_programs"] == 0

    def test_referrals_with_program(self, client):
        pipeline.referral_engine.create_program(
            platform_id="default", name="Growth Hack"
        )
        resp = client.get("/api/v1/analytics/referrals")
        assert resp.status_code == 200
        assert resp.json()["total_programs"] == 1


class TestAudiencesAnalyticsEndpoint:

    def test_audiences_empty(self, client):
        resp = client.get("/api/v1/analytics/audiences")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_audiences"] == 0


class TestGrowthEndpoint:

    def test_growth(self, client):
        _seed_profiles()
        resp = client.get("/api/v1/analytics/growth")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_users"] == 3
        assert data["active_users"] == 2
        assert "new_users_7d" in data
        assert "dau_mau_ratio" in data


class TestAdminHealthEndpoint:

    def test_health(self, client):
        resp = client.get("/api/v1/admin/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "components" in data
        assert "total_platforms" in data
        assert "computed_at" in data


class TestAdminPlatformsEndpoint:

    def test_list_empty(self, client):
        resp = client.get("/api/v1/admin/platforms")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_with_platforms(self, client):
        pipeline.platform_registry.register(
            name="TestPlat", slug="test-plat", owner_email="t@t.com"
        )
        resp = client.get("/api/v1/admin/platforms")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "TestPlat"


class TestAdminPlatformDetailEndpoint:

    def test_not_found(self, client):
        resp = client.get("/api/v1/admin/platforms/nonexistent")
        assert resp.status_code == 404

    def test_detail(self, client):
        plat, _, _ = pipeline.platform_registry.register(
            name="Detail", slug="detail-test", owner_email="d@d.com"
        )
        resp = client.get(f"/api/v1/admin/platforms/{plat.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Detail"
        assert "quotas" in data


class TestAdminPlatformUpdateEndpoint:

    def test_not_found(self, client):
        resp = client.put(
            "/api/v1/admin/platforms/fake", json={"name": "New"}
        )
        assert resp.status_code == 404

    def test_update(self, client):
        plat, _, _ = pipeline.platform_registry.register(
            name="Old", slug="update-test", owner_email="u@u.com"
        )
        resp = client.put(
            f"/api/v1/admin/platforms/{plat.id}",
            json={"name": "Updated"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated"


class TestAdminStatsEndpoint:

    def test_stats(self, client):
        resp = client.get("/api/v1/admin/stats")
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)
