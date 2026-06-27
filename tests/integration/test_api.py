"""
Integration test — full UGIE pipeline via HTTP.

Proves: event ingestion → identity resolution → behavioral profiling →
prediction → decision — all through the REST API with SQLite persistence.
"""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from api.rest.app import create_app, pipeline


@pytest.fixture(scope="module")
def client():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{db_path}"

    app = create_app(db_url=db_url)
    with TestClient(app) as c:
        yield c

    try:
        os.unlink(db_path)
    except OSError:
        pass


class TestHealthEndpoints:

    def test_health(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.1.0"

    def test_stats(self, client):
        resp = client.get("/api/v1/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "event_bus" in data


class TestFullPipeline:

    def test_end_to_end(self, client):
        app_id = "test_app"

        # 1. USER_REGISTERED — creates identity
        resp = client.post("/api/v1/events", json={
            "application_id": app_id,
            "type": "USER_REGISTERED",
            "actor_id": "user_001",
            "actor_type": "User",
            "properties": {"email": "alice@example.com"},
        })
        assert resp.status_code == 200
        result = resp.json()
        assert result["success"] is True

        # 2. SESSION_STARTED
        resp = client.post("/api/v1/events", json={
            "application_id": app_id,
            "type": "SESSION_STARTED",
            "actor_id": "user_001",
            "actor_type": "User",
            "properties": {},
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # 3. PAGE_VIEWED
        resp = client.post("/api/v1/events", json={
            "application_id": app_id,
            "type": "PAGE_VIEWED",
            "actor_id": "user_001",
            "actor_type": "User",
            "properties": {"page_url": "/products/shoes"},
        })
        assert resp.status_code == 200

        # 4. PAYMENT_COMPLETED
        resp = client.post("/api/v1/events", json={
            "application_id": app_id,
            "type": "PAYMENT_COMPLETED",
            "actor_id": "user_001",
            "actor_type": "User",
            "properties": {"amount": 99.99, "currency": "USD"},
        })
        assert resp.status_code == 200

        # 5. Look up identity by email
        resp = client.get("/api/v1/identities/by-email/alice@example.com")
        assert resp.status_code == 200
        identity = resp.json()
        identity_id = identity["id"]
        assert identity["canonical_email"] == "alice@example.com"
        assert app_id in identity["application_ids"]

        # 6. Get identity by ID
        resp = client.get(f"/api/v1/identities/{identity_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == identity_id

        # 7. Get behavioral profile
        resp = client.get(f"/api/v1/identities/{identity_id}/profile")
        assert resp.status_code == 200
        profile = resp.json()
        assert profile["identity_id"] == identity_id
        assert profile["engagement"]["total_events"] >= 4
        assert profile["engagement"]["total_sessions"] >= 1
        assert profile["rfm"]["total_conversions"] >= 1
        assert profile["rfm"]["total_monetary_value"] >= 99.99

        # 8. Request decision
        resp = client.post("/api/v1/decide", json={
            "identity_id": identity_id,
            "application_id": app_id,
            "trigger_event_type": "PAYMENT_COMPLETED",
        })
        assert resp.status_code == 200
        decision_data = resp.json()
        assert "decisions" in decision_data

        # 9. Get decision history
        resp = client.get(f"/api/v1/decisions/{identity_id}")
        assert resp.status_code == 200


class TestEntityEndpoints:

    def test_entity_crud(self, client):
        resp = client.post("/api/v1/entities", json={
            "application_id": "test_app",
            "type_name": "Product",
            "attributes": {"name": "Test Product", "price": 29.99},
            "tags": ["featured"],
        })
        assert resp.status_code == 200
        entity = resp.json()
        entity_id = entity["id"]

        resp = client.get(f"/api/v1/entities/{entity_id}")
        assert resp.status_code == 200
        assert resp.json()["attributes"]["name"] == "Test Product"

        resp = client.get("/api/v1/entities", params={
            "application_id": "test_app",
            "type_name": "Product",
        })
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

        resp = client.delete(f"/api/v1/entities/{entity_id}")
        assert resp.status_code == 200

        resp = client.get(f"/api/v1/entities/{entity_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

    def test_entity_not_found(self, client):
        resp = client.get("/api/v1/entities/nonexistent")
        assert resp.status_code == 404


class TestBatchEvents:

    def test_batch_submit(self, client):
        events = [
            {
                "application_id": "batch_app",
                "type": "SESSION_STARTED",
                "actor_id": "batch_user",
                "actor_type": "User",
                "properties": {},
            },
            {
                "application_id": "batch_app",
                "type": "PAGE_VIEWED",
                "actor_id": "batch_user",
                "actor_type": "User",
                "properties": {"page_url": "/home"},
            },
        ]
        resp = client.post("/api/v1/events/batch", json=events)
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) == 2
        assert all(r["success"] for r in results)


class TestErrorHandling:

    def test_invalid_event_type(self, client):
        resp = client.post("/api/v1/events", json={
            "application_id": "test_app",
            "type": "TOTALLY_FAKE",
            "properties": {},
        })
        assert resp.status_code == 400

    def test_identity_not_found(self, client):
        resp = client.get("/api/v1/identities/nonexistent")
        assert resp.status_code == 404
