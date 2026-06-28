"""
Integration tests for acquisition plan refresh (cold → warm mode transition).
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from api.rest.app import create_app, pipeline
from core.behavior.schema import BehavioralProfile


def _slug():
    return f"ar-{uuid.uuid4().hex[:10]}"


@pytest.fixture(scope="module")
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


class TestAcquisitionPlanRefresh:

    def test_refresh_cold_plan_stays_cold_with_no_profiles(self, client):
        resp = client.post("/api/v1/platforms", json={
            "name": "Empty Platform",
            "slug": _slug(),
            "owner_email": "admin@empty.io",
            "category_hint": "saas",
        })
        platform_id = resp.json()["id"]

        refresh = client.post(f"/api/v1/platforms/{platform_id}/acquisition-plan/refresh")
        assert refresh.status_code == 200
        data = refresh.json()
        assert data["stage"] == "cold"
        assert len(data["lookalike_seeds"]) == 0

    def test_refresh_transitions_to_warm_with_profiles(self, client):
        resp = client.post("/api/v1/platforms", json={
            "name": "Growing Platform",
            "slug": _slug(),
            "owner_email": "admin@grow.io",
            "category_hint": "ecommerce",
        })
        platform_id = resp.json()["id"]

        for i in range(20):
            p = BehavioralProfile(
                identity_id=f"user_{i}",
                application_id=platform_id,
            )
            p.rfm.total_monetary_value = float(i * 100)
            p.rfm.segment = "champions" if i >= 15 else "new"
            pipeline.behavior_repo.save(p)

        refresh = client.post(f"/api/v1/platforms/{platform_id}/acquisition-plan/refresh")
        assert refresh.status_code == 200
        data = refresh.json()
        assert data["stage"] == "warm"
        assert len(data["lookalike_seeds"]) >= 2

    def test_warm_plan_has_lookalike_platforms(self, client):
        resp = client.post("/api/v1/platforms", json={
            "name": "Warm Platform",
            "slug": _slug(),
            "owner_email": "admin@warm.io",
            "category_hint": "b2b_marketplace",
        })
        platform_id = resp.json()["id"]

        for i in range(15):
            p = BehavioralProfile(
                identity_id=f"warm_user_{i}",
                application_id=platform_id,
            )
            p.rfm.total_monetary_value = float(i * 200)
            pipeline.behavior_repo.save(p)

        refresh = client.post(f"/api/v1/platforms/{platform_id}/acquisition-plan/refresh")
        data = refresh.json()
        platforms = [ls["platform"] for ls in data["lookalike_seeds"]]
        assert "meta" in platforms
        assert "google" in platforms

    def test_refresh_not_found_without_cold_start(self, client):
        resp = client.post(f"/api/v1/platforms/nonexistent/acquisition-plan/refresh")
        assert resp.status_code == 404

    def test_channel_plans_present_after_refresh(self, client):
        resp = client.post("/api/v1/platforms", json={
            "name": "Channel Test",
            "slug": _slug(),
            "owner_email": "admin@ch.io",
            "category_hint": "healthtech",
        })
        platform_id = resp.json()["id"]

        for i in range(12):
            p = BehavioralProfile(
                identity_id=f"ch_user_{i}",
                application_id=platform_id,
            )
            p.rfm.total_monetary_value = float(i * 50)
            pipeline.behavior_repo.save(p)

        refresh = client.post(f"/api/v1/platforms/{platform_id}/acquisition-plan/refresh")
        data = refresh.json()
        assert len(data["channel_plans"]) >= 3
        for cp in data["channel_plans"]:
            assert "targeting" in cp
            assert "creative" in cp
            assert cp["creative"]["headline"]
            assert cp["creative"]["cta"]

    def test_lookalike_seed_count_reflects_top_profiles(self, client):
        resp = client.post("/api/v1/platforms", json={
            "name": "Seed Count Test",
            "slug": _slug(),
            "owner_email": "admin@seed.io",
            "category_hint": "fintech_payments",
        })
        platform_id = resp.json()["id"]

        for i in range(30):
            p = BehavioralProfile(
                identity_id=f"seed_user_{i}",
                application_id=platform_id,
            )
            p.rfm.total_monetary_value = float(i * 300)
            pipeline.behavior_repo.save(p)

        refresh = client.post(f"/api/v1/platforms/{platform_id}/acquisition-plan/refresh")
        data = refresh.json()
        for ls in data["lookalike_seeds"]:
            assert ls["seed_count"] == 3
