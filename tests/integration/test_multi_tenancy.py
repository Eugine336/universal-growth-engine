"""
Integration tests for multi-tenancy — platform registration, API key auth,
and tenant isolation across the REST API.
"""

import os
import tempfile
import uuid

import pytest
from fastapi.testclient import TestClient

from api.rest.app import create_app, pipeline


def _slug():
    return f"t-{uuid.uuid4().hex[:10]}"


@pytest.fixture(scope="module")
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


# ======================================================================
# Platform Registration
# ======================================================================

class TestPlatformRegistration:

    def test_register_platform(self, client):
        resp = client.post("/api/v1/platforms", json={
            "name": "UCMC Marketplace",
            "slug": _slug(),
            "owner_email": "admin@ucmc.io",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "UCMC Marketplace"
        assert data["status"] == "active"
        assert "api_key" in data
        assert data["api_key"].startswith("ugie_")
        assert data["api_key_prefix"] == data["api_key"][:8]

    def test_register_duplicate_slug_fails(self, client):
        slug = _slug()
        client.post("/api/v1/platforms", json={
            "name": "First", "slug": slug, "owner_email": "a@b.com",
        })
        resp = client.post("/api/v1/platforms", json={
            "name": "Second", "slug": slug, "owner_email": "c@d.com",
        })
        assert resp.status_code == 400
        assert "already taken" in resp.json()["detail"]

    def test_register_invalid_slug_fails(self, client):
        resp = client.post("/api/v1/platforms", json={
            "name": "Bad", "slug": "X", "owner_email": "a@b.com",
        })
        assert resp.status_code == 400

    def test_register_with_custom_quotas(self, client):
        resp = client.post("/api/v1/platforms", json={
            "name": "Custom", "slug": _slug(),
            "owner_email": "a@b.com",
            "max_events_per_hour": 500,
        })
        assert resp.status_code == 200
        assert resp.json()["quotas"]["max_events_per_hour"] == 500


# ======================================================================
# API Key Authentication
# ======================================================================

class TestApiKeyAuth:

    @pytest.fixture(autouse=True)
    def setup_platform(self, client):
        resp = client.post("/api/v1/platforms", json={
            "name": "Auth Test", "slug": _slug(), "owner_email": "a@b.com",
        })
        self.api_key = resp.json()["api_key"]
        self.platform_id = resp.json()["id"]

    def test_get_me_with_valid_key(self, client):
        resp = client.get(
            "/api/v1/platforms/me",
            headers={"X-API-Key": self.api_key},
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == self.platform_id

    def test_get_me_without_key_returns_401(self, client):
        resp = client.get("/api/v1/platforms/me")
        assert resp.status_code == 401

    def test_get_me_with_invalid_key_returns_401(self, client):
        resp = client.get(
            "/api/v1/platforms/me",
            headers={"X-API-Key": "ugie_fakefakefakefakefakefakefake00"},
        )
        assert resp.status_code == 401

    def test_bearer_auth(self, client):
        resp = client.get(
            "/api/v1/platforms/me",
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == self.platform_id

    def test_suspended_platform_returns_403(self, client):
        pipeline.platform_registry.suspend(self.platform_id)
        resp = client.get(
            "/api/v1/platforms/me",
            headers={"X-API-Key": self.api_key},
        )
        assert resp.status_code == 403


# ======================================================================
# Platform Management
# ======================================================================

class TestPlatformManagement:

    @pytest.fixture(autouse=True)
    def setup_platform(self, client):
        resp = client.post("/api/v1/platforms", json={
            "name": "Mgmt Test", "slug": _slug(), "owner_email": "a@b.com",
        })
        self.api_key = resp.json()["api_key"]
        self.platform_id = resp.json()["id"]

    def test_update_platform(self, client):
        resp = client.put(
            "/api/v1/platforms/me",
            headers={"X-API-Key": self.api_key},
            json={"name": "Updated Name"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Name"

    def test_update_quotas(self, client):
        resp = client.put(
            "/api/v1/platforms/me",
            headers={"X-API-Key": self.api_key},
            json={"max_events_per_hour": 999},
        )
        assert resp.status_code == 200
        assert resp.json()["quotas"]["max_events_per_hour"] == 999

    def test_rotate_key(self, client):
        resp = client.post(
            "/api/v1/platforms/me/rotate-key",
            headers={"X-API-Key": self.api_key},
        )
        assert resp.status_code == 200
        new_key = resp.json()["api_key"]
        assert new_key != self.api_key

        old_resp = client.get(
            "/api/v1/platforms/me",
            headers={"X-API-Key": self.api_key},
        )
        assert old_resp.status_code == 401

        new_resp = client.get(
            "/api/v1/platforms/me",
            headers={"X-API-Key": new_key},
        )
        assert new_resp.status_code == 200

    def test_platform_stats(self, client):
        resp = client.get(
            "/api/v1/platforms/me/stats",
            headers={"X-API-Key": self.api_key},
        )
        assert resp.status_code == 200
        assert "platform_id" in resp.json()


# ======================================================================
# Tenant Isolation
# ======================================================================

class TestTenantIsolation:

    @pytest.fixture(autouse=True)
    def setup_two_platforms(self, client):
        resp_a = client.post("/api/v1/platforms", json={
            "name": "Platform A", "slug": _slug(), "owner_email": "a@a.com",
        })
        self.key_a = resp_a.json()["api_key"]
        self.id_a = resp_a.json()["id"]

        resp_b = client.post("/api/v1/platforms", json={
            "name": "Platform B", "slug": _slug(), "owner_email": "b@b.com",
        })
        self.key_b = resp_b.json()["api_key"]
        self.id_b = resp_b.json()["id"]

    def test_entity_scoped_to_platform(self, client):
        create_resp = client.post(
            "/api/v1/entities",
            headers={"X-API-Key": self.key_a},
            json={
                "application_id": "ignored",
                "type_name": "Seller",
                "attributes": {"name": "Jane"},
            },
        )
        assert create_resp.status_code == 200
        entity_id = create_resp.json()["id"]
        assert create_resp.json()["application_id"] == self.id_a

        get_a = client.get(
            f"/api/v1/entities/{entity_id}",
            headers={"X-API-Key": self.key_a},
        )
        assert get_a.status_code == 200

        get_b = client.get(
            f"/api/v1/entities/{entity_id}",
            headers={"X-API-Key": self.key_b},
        )
        assert get_b.status_code == 404

    def test_entity_list_scoped(self, client):
        client.post(
            "/api/v1/entities",
            headers={"X-API-Key": self.key_a},
            json={"application_id": "x", "type_name": "Buyer"},
        )
        client.post(
            "/api/v1/entities",
            headers={"X-API-Key": self.key_b},
            json={"application_id": "x", "type_name": "Buyer"},
        )
        list_a = client.get(
            "/api/v1/entities?type_name=Buyer",
            headers={"X-API-Key": self.key_a},
        )
        list_b = client.get(
            "/api/v1/entities?type_name=Buyer",
            headers={"X-API-Key": self.key_b},
        )
        ids_a = {e["application_id"] for e in list_a.json()}
        ids_b = {e["application_id"] for e in list_b.json()}
        assert ids_a == {self.id_a}
        assert ids_b == {self.id_b}

    def test_event_scoped_to_platform(self, client):
        resp = client.post(
            "/api/v1/events",
            headers={"X-API-Key": self.key_a},
            json={
                "application_id": "should_be_overridden",
                "type": "PAGE_VIEWED",
                "actor_id": "user1",
                "properties": {"page_name": "home"},
            },
        )
        assert resp.status_code == 200

    def test_delete_entity_scoped(self, client):
        create = client.post(
            "/api/v1/entities",
            headers={"X-API-Key": self.key_a},
            json={"application_id": "x", "type_name": "Listing"},
        )
        eid = create.json()["id"]

        del_b = client.delete(
            f"/api/v1/entities/{eid}",
            headers={"X-API-Key": self.key_b},
        )
        assert del_b.status_code == 404

        del_a = client.delete(
            f"/api/v1/entities/{eid}",
            headers={"X-API-Key": self.key_a},
        )
        assert del_a.status_code == 200


# ======================================================================
# Backward Compatibility
# ======================================================================

class TestBackwardCompatibility:

    def test_events_work_without_api_key(self, client):
        resp = client.post("/api/v1/events", json={
            "application_id": "legacy_app",
            "type": "PAGE_VIEWED",
            "actor_id": "u1",
            "properties": {"page_name": "landing"},
        })
        assert resp.status_code == 200

    def test_entities_work_without_api_key(self, client):
        resp = client.post("/api/v1/entities", json={
            "application_id": "legacy_app",
            "type_name": "User",
        })
        assert resp.status_code == 200
        assert resp.json()["application_id"] == "legacy_app"

    def test_health_works_without_api_key(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200

    def test_entity_list_without_key_uses_query_param(self, client):
        client.post("/api/v1/entities", json={
            "application_id": "compat_app",
            "type_name": "Widget",
        })
        resp = client.get("/api/v1/entities?application_id=compat_app&type_name=Widget")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_decide_without_key_uses_body(self, client):
        resp = client.post("/api/v1/decide", json={
            "identity_id": "id123",
            "application_id": "compat_app",
        })
        assert resp.status_code == 200


# ======================================================================
# Config Upload
# ======================================================================

class TestConfigUpload:

    @pytest.fixture(autouse=True)
    def setup_platform(self, client):
        resp = client.post("/api/v1/platforms", json={
            "name": "Config Test", "slug": _slug(), "owner_email": "a@b.com",
        })
        self.api_key = resp.json()["api_key"]

    def test_upload_valid_config(self, client):
        yaml_content = """
application:
  id: test-app
  name: Test Application
  category: testing
entities:
  - type_name: Widget
    description: A widget
"""
        resp = client.post(
            "/api/v1/platforms/me/config",
            headers={"X-API-Key": self.api_key},
            json={"yaml_content": yaml_content},
        )
        assert resp.status_code == 200
        assert resp.json()["application_id"] == "test-app"
        assert resp.json()["entities"] == 1

    def test_upload_invalid_config(self, client):
        resp = client.post(
            "/api/v1/platforms/me/config",
            headers={"X-API-Key": self.api_key},
            json={"yaml_content": "not: valid: yaml: [[["},
        )
        assert resp.status_code == 400
