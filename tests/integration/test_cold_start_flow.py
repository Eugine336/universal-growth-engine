"""
Integration tests for the full cold start flow:
  Register platform → classify → playbook → policies → first user → decisions fire.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from api.rest.app import create_app, pipeline


def _slug():
    return f"cs-{uuid.uuid4().hex[:10]}"


@pytest.fixture(scope="module")
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


class TestColdStartOnRegistration:

    def test_register_returns_cold_start(self, client):
        resp = client.post("/api/v1/platforms", json={
            "name": "AI Marketplace",
            "slug": _slug(),
            "owner_email": "admin@ucmc.io",
            "entity_types": ["Seller", "Buyer", "Listing", "Escrow"],
            "objectives": ["GMV", "marketplace liquidity"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "cold_start" in data
        cs = data["cold_start"]
        assert cs["category"] == "b2b_marketplace"
        assert cs["confidence"] > 0.3
        assert cs["policies_registered"] >= 5

    def test_register_with_hint(self, client):
        resp = client.post("/api/v1/platforms", json={
            "name": "FitNaija",
            "slug": _slug(),
            "owner_email": "admin@fit.ng",
            "category_hint": "healthtech",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["cold_start"]["category"] == "healthtech"
        assert data["cold_start"]["confidence"] == 1.0

    def test_register_generic_fallback(self, client):
        resp = client.post("/api/v1/platforms", json={
            "name": "Unknown App",
            "slug": _slug(),
            "owner_email": "admin@app.com",
            "entity_types": ["Widget"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["cold_start"]["category"] == "generic"
        assert data["cold_start"]["policies_registered"] >= 4


class TestColdStartEndpoints:

    def test_get_cold_start_result(self, client):
        resp = client.post("/api/v1/platforms", json={
            "name": "SaaS Tool",
            "slug": _slug(),
            "owner_email": "admin@saas.io",
            "entity_types": ["User", "Workspace", "Subscription"],
            "objectives": ["MRR", "retention"],
        })
        platform_id = resp.json()["id"]

        result = client.get(f"/api/v1/platforms/{platform_id}/cold-start")
        assert result.status_code == 200
        data = result.json()
        assert data["platform_id"] == platform_id
        assert data["category"]["category_id"] == "saas"
        assert data["policies_registered"] >= 4

    def test_get_playbook(self, client):
        resp = client.post("/api/v1/platforms", json={
            "name": "EdTech Platform",
            "slug": _slug(),
            "owner_email": "admin@ed.io",
            "category_hint": "edtech",
        })
        platform_id = resp.json()["id"]

        pb = client.get(f"/api/v1/platforms/{platform_id}/playbook")
        assert pb.status_code == 200
        data = pb.json()
        assert data["platform_id"] == platform_id
        assert data["stage"] == "pre_launch"
        assert len(data["acquisition_channels"]) >= 3
        assert len(data["activation_sequence"]) >= 4
        assert data["value_proposition"]
        assert data["cold_start_window_days"] > 0

    def test_get_acquisition_plan(self, client):
        resp = client.post("/api/v1/platforms", json={
            "name": "Trading Platform",
            "slug": _slug(),
            "owner_email": "admin@trade.io",
            "category_hint": "fintech_trading",
        })
        platform_id = resp.json()["id"]

        plan = client.get(f"/api/v1/platforms/{platform_id}/acquisition-plan")
        assert plan.status_code == 200
        data = plan.json()
        assert data["platform_id"] == platform_id
        assert data["stage"] == "cold"
        assert len(data["channel_plans"]) >= 3
        assert data["estimated_cac"] > 0
        assert len(data["lookalike_seeds"]) == 0

    def test_cold_start_not_found(self, client):
        resp = client.get("/api/v1/platforms/nonexistent-id/cold-start")
        assert resp.status_code == 404

    def test_playbook_not_found(self, client):
        resp = client.get("/api/v1/platforms/nonexistent-id/playbook")
        assert resp.status_code == 404


class TestPoliciesFire:

    def test_activation_policies_registered_in_decision_engine(self, client):
        slug = _slug()
        resp = client.post("/api/v1/platforms", json={
            "name": "B2B Market",
            "slug": slug,
            "owner_email": "admin@market.io",
            "entity_types": ["Seller", "Buyer", "Listing"],
            "objectives": ["GMV"],
        })
        platform_id = resp.json()["id"]

        policies = pipeline.decision_engine._registry.list_for_application(platform_id)
        activation_policies = [p for p in policies if p.application_id == platform_id]
        assert len(activation_policies) >= 5

        names = [p.name for p in activation_policies]
        assert "Welcome & Profile Completion" in names

    def test_welcome_policy_matches_user_registered(self, client):
        slug = _slug()
        resp = client.post("/api/v1/platforms", json={
            "name": "Test Platform",
            "slug": slug,
            "owner_email": "admin@test.io",
            "category_hint": "saas",
        })
        platform_id = resp.json()["id"]

        policies = pipeline.decision_engine._registry.get_active(
            platform_id, trigger_event="USER_REGISTERED"
        )
        welcome = [p for p in policies if "Welcome" in p.name and p.application_id == platform_id]
        assert len(welcome) >= 1

    def test_reengagement_policy_has_abort_conditions(self, client):
        slug = _slug()
        resp = client.post("/api/v1/platforms", json={
            "name": "Abort Test",
            "slug": slug,
            "owner_email": "admin@test.io",
            "category_hint": "ecommerce",
        })
        platform_id = resp.json()["id"]

        policies = pipeline.decision_engine._registry.list_for_application(platform_id)
        reeng = [p for p in policies if "48h" in p.name and p.application_id == platform_id]
        assert len(reeng) >= 1
        assert "SESSION_STARTED" in reeng[0].abort_if_events
