"""Integration tests for Budget Allocator API endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.rest.app import create_app, pipeline


@pytest.fixture()
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    if pipeline.budget_allocator:
        pipeline.budget_allocator._plans.clear()
        pipeline.budget_allocator._performance.clear()
        pipeline.budget_allocator._history.clear()
    if pipeline.platform_registry:
        pipeline.platform_registry._platforms.clear()
        pipeline.platform_registry._slug_index.clear()
        pipeline.platform_registry._key_index.clear()


class TestCreatePlanEndpoint:

    def test_create_basic(self, client):
        resp = client.post(
            "/api/v1/budget/plans?platform_id=test",
            json={"total_budget": 1000.0},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["platform_id"] == "test"
        assert data["total_budget"] == 1000.0
        assert data["status"] == "active"

    def test_create_with_channels(self, client):
        resp = client.post(
            "/api/v1/budget/plans?platform_id=test",
            json={
                "total_budget": 3000.0,
                "channel_allocations": {
                    "email": 1000.0,
                    "meta_ads": 1500.0,
                    "referral": 500.0,
                },
                "reallocation_strategy": "winner_takes_more",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["channel_budgets"]) == 3
        assert data["reallocation_strategy"] == "winner_takes_more"

    def test_create_with_configs(self, client):
        resp = client.post(
            "/api/v1/budget/plans?platform_id=test",
            json={
                "total_budget": 2000.0,
                "channel_allocations": {"email": 1000.0, "sms": 1000.0},
                "channel_configs": {
                    "email": {"auto_pause_threshold": 50.0, "min_budget": 100.0},
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["channel_budgets"]["email"]["auto_pause_threshold"] == 50.0
        assert data["channel_budgets"]["email"]["min_budget"] == 100.0


class TestGetPlanEndpoint:

    def test_get_existing(self, client):
        client.post(
            "/api/v1/budget/plans?platform_id=test",
            json={"total_budget": 1000.0},
        )
        resp = client.get("/api/v1/budget/plans?platform_id=test")
        assert resp.status_code == 200
        assert resp.json()["total_budget"] == 1000.0

    def test_get_not_found(self, client):
        resp = client.get("/api/v1/budget/plans?platform_id=nope")
        assert resp.status_code == 404


class TestUpdatePlanEndpoint:

    def test_update(self, client):
        client.post(
            "/api/v1/budget/plans?platform_id=test",
            json={"total_budget": 1000.0},
        )
        resp = client.put(
            "/api/v1/budget/plans?platform_id=test",
            json={"total_budget": 2000.0, "period": "weekly"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_budget"] == 2000.0
        assert data["period"] == "weekly"

    def test_update_not_found(self, client):
        resp = client.put(
            "/api/v1/budget/plans?platform_id=nope",
            json={"total_budget": 500.0},
        )
        assert resp.status_code == 404


class TestPerformanceEndpoints:

    def _seed_actions(self, client):
        client.post(
            "/api/v1/budget/plans?platform_id=default",
            json={
                "total_budget": 1000.0,
                "channel_allocations": {"email": 500.0, "sms": 500.0},
            },
        )
        pipeline.budget_allocator.record_action("default", "email", cost=10.0, success=True)
        pipeline.budget_allocator.record_action("default", "sms", cost=5.0, success=True)
        pipeline.budget_allocator.record_conversion("default", "email")

    def test_all_performance(self, client):
        self._seed_actions(client)
        resp = client.get("/api/v1/budget/performance")
        assert resp.status_code == 200
        data = resp.json()
        assert "email" in data
        assert "sms" in data
        assert data["email"]["conversions"] == 1
        assert data["email"]["cac"] == 10.0

    def test_single_channel(self, client):
        self._seed_actions(client)
        resp = client.get("/api/v1/budget/performance/email")
        assert resp.status_code == 200
        data = resp.json()
        assert data["channel"] == "email"
        assert data["total_actions"] == 1
        assert data["conversions"] == 1

    def test_channel_not_found(self, client):
        resp = client.get("/api/v1/budget/performance/nonexistent")
        assert resp.status_code == 404


class TestOptimizeEndpoint:

    def test_no_changes(self, client):
        client.post(
            "/api/v1/budget/plans?platform_id=default",
            json={"total_budget": 1000.0},
        )
        resp = client.post("/api/v1/budget/optimize")
        assert resp.status_code == 200
        assert resp.json()["status"] == "no_changes"

    def test_triggers_reallocation(self, client):
        client.post(
            "/api/v1/budget/plans?platform_id=default",
            json={
                "total_budget": 2000.0,
                "channel_allocations": {"email": 1000.0, "sms": 1000.0},
                "channel_configs": {
                    "email": {"auto_pause_threshold": 10.0},
                    "sms": {"auto_pause_threshold": 200.0},
                },
            },
        )
        for _ in range(10):
            pipeline.budget_allocator.record_action("default", "email", cost=20.0, success=True)
        for _ in range(10):
            pipeline.budget_allocator.record_conversion("default", "email")
        for _ in range(5):
            pipeline.budget_allocator.record_action("default", "sms", cost=5.0, success=True)
        for _ in range(5):
            pipeline.budget_allocator.record_conversion("default", "sms")

        resp = client.post("/api/v1/budget/optimize")
        assert resp.status_code == 200
        data = resp.json()
        assert "changes" in data
        assert len(data["changes"]) > 0


class TestRecommendationEndpoint:

    def test_no_plan(self, client):
        resp = client.get("/api/v1/budget/recommendation?platform_id=nope")
        assert resp.status_code == 200
        data = resp.json()
        assert data["recommendation"] is None

    def test_with_data(self, client):
        client.post(
            "/api/v1/budget/plans?platform_id=default",
            json={
                "total_budget": 2000.0,
                "channel_allocations": {"email": 1000.0, "sms": 1000.0},
                "channel_configs": {
                    "email": {"auto_pause_threshold": 10.0},
                    "sms": {"auto_pause_threshold": 200.0},
                },
            },
        )
        for _ in range(10):
            pipeline.budget_allocator.record_action("default", "email", cost=20.0, success=True)
        for _ in range(10):
            pipeline.budget_allocator.record_conversion("default", "email")
        for _ in range(5):
            pipeline.budget_allocator.record_action("default", "sms", cost=5.0, success=True)
        for _ in range(5):
            pipeline.budget_allocator.record_conversion("default", "sms")

        resp = client.get("/api/v1/budget/recommendation")
        assert resp.status_code == 200
        data = resp.json()
        assert data["would_reallocate"] is True


class TestHistoryEndpoint:

    def test_empty(self, client):
        resp = client.get("/api/v1/budget/history")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_after_optimization(self, client):
        client.post(
            "/api/v1/budget/plans?platform_id=default",
            json={
                "total_budget": 2000.0,
                "channel_allocations": {"email": 1000.0, "sms": 1000.0},
                "channel_configs": {
                    "email": {"auto_pause_threshold": 10.0},
                    "sms": {"auto_pause_threshold": 200.0},
                },
            },
        )
        for _ in range(10):
            pipeline.budget_allocator.record_action("default", "email", cost=20.0, success=True)
        for _ in range(10):
            pipeline.budget_allocator.record_conversion("default", "email")
        for _ in range(5):
            pipeline.budget_allocator.record_action("default", "sms", cost=5.0, success=True)
        for _ in range(5):
            pipeline.budget_allocator.record_conversion("default", "sms")

        client.post("/api/v1/budget/optimize")
        resp = client.get("/api/v1/budget/history")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["trigger"] == "auto"


class TestPauseResumeEndpoints:

    def _create_plan(self, client):
        client.post(
            "/api/v1/budget/plans?platform_id=default",
            json={
                "total_budget": 1000.0,
                "channel_allocations": {"email": 500.0, "sms": 500.0},
            },
        )

    def test_pause(self, client):
        self._create_plan(client)
        resp = client.post("/api/v1/budget/channels/email/pause")
        assert resp.status_code == 200
        data = resp.json()
        assert data["channel_budgets"]["email"]["status"] == "paused"

    def test_resume(self, client):
        self._create_plan(client)
        client.post("/api/v1/budget/channels/email/pause")
        resp = client.post("/api/v1/budget/channels/email/resume")
        assert resp.status_code == 200
        data = resp.json()
        assert data["channel_budgets"]["email"]["status"] == "active"

    def test_pause_not_found(self, client):
        resp = client.post(
            "/api/v1/budget/channels/email/pause?platform_id=nope"
        )
        assert resp.status_code == 404

    def test_resume_not_found(self, client):
        resp = client.post(
            "/api/v1/budget/channels/email/resume?platform_id=nope"
        )
        assert resp.status_code == 404


class TestStatsEndpoint:

    def test_empty(self, client):
        resp = client.get("/api/v1/budget/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_plans"] == 0
        assert data["total_spend"] == 0

    def test_with_data(self, client):
        client.post(
            "/api/v1/budget/plans?platform_id=default",
            json={"total_budget": 1000.0},
        )
        pipeline.budget_allocator.record_action("default", "email", cost=50.0)
        pipeline.budget_allocator.record_conversion("default", "email")
        resp = client.get("/api/v1/budget/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_plans"] == 1
        assert data["total_spend"] == 50.0
        assert data["total_conversions"] == 1


class TestFullFlow:

    def test_end_to_end(self, client):
        resp = client.post(
            "/api/v1/budget/plans?platform_id=default",
            json={
                "total_budget": 3000.0,
                "channel_allocations": {
                    "email": 1000.0,
                    "meta_ads": 1000.0,
                    "google_ads": 1000.0,
                },
                "channel_configs": {
                    "email": {"auto_pause_threshold": 100.0},
                    "meta_ads": {"auto_pause_threshold": 100.0},
                    "google_ads": {"auto_pause_threshold": 100.0},
                },
                "reallocation_strategy": "proportional",
            },
        )
        assert resp.status_code == 200

        # email: good (CAC $5)
        for _ in range(20):
            pipeline.budget_allocator.record_action("default", "email", cost=5.0, success=True)
        for _ in range(20):
            pipeline.budget_allocator.record_conversion("default", "email")

        # meta_ads: ok (CAC $50)
        for _ in range(10):
            pipeline.budget_allocator.record_action("default", "meta_ads", cost=50.0, success=True)
        for _ in range(10):
            pipeline.budget_allocator.record_conversion("default", "meta_ads")

        # google_ads: bad (CAC $200), only 3 actions to leave remaining budget
        for _ in range(3):
            pipeline.budget_allocator.record_action("default", "google_ads", cost=200.0, success=True)
        for _ in range(3):
            pipeline.budget_allocator.record_conversion("default", "google_ads")

        # Check performance
        resp = client.get("/api/v1/budget/performance")
        assert resp.status_code == 200
        perf = resp.json()
        assert perf["email"]["cac"] == 5.0
        assert perf["meta_ads"]["cac"] == 50.0
        assert perf["google_ads"]["cac"] == 200.0

        # Check recommendation
        resp = client.get("/api/v1/budget/recommendation")
        assert resp.status_code == 200
        rec = resp.json()
        assert rec["would_reallocate"] is True

        # Run optimization
        resp = client.post("/api/v1/budget/optimize")
        assert resp.status_code == 200
        opt = resp.json()
        assert "changes" in opt

        # Verify google_ads paused
        resp = client.get("/api/v1/budget/plans?platform_id=default")
        assert resp.status_code == 200
        plan = resp.json()
        assert plan["channel_budgets"]["google_ads"]["status"] == "paused"
        assert plan["channel_budgets"]["email"]["allocated_budget"] > 1000.0
        assert plan["channel_budgets"]["meta_ads"]["allocated_budget"] > 1000.0

        # Check history
        resp = client.get("/api/v1/budget/history")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

        # Check stats
        resp = client.get("/api/v1/budget/stats")
        assert resp.status_code == 200
        stats = resp.json()
        assert stats["total_plans"] == 1
        assert stats["total_reallocations"] == 1
