"""
Integration tests for the Audience API endpoints.
"""

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
def _seed_profiles():
    """Seed behavioral profiles before each test."""
    yield
    if pipeline.behavior_repo:
        pipeline.behavior_repo._profiles.clear()
    if pipeline.audience_engine:
        pipeline.audience_engine._audiences.clear()
    if pipeline.audience_exporter:
        pipeline.audience_exporter._jobs.clear()


def _seed(client):
    from core.behavior.schema import BehavioralProfile, IntentSignal

    repo = pipeline.behavior_repo

    p1 = BehavioralProfile(identity_id="u1", application_id="app1")
    p1.engagement.tier = "power"
    p1.engagement.sessions_last_30d = 20
    p1.rfm.segment = "champions"
    p1.rfm.combined_score = 14
    p1.churn.risk_level = "low"
    p1.traits["is_paying"] = True
    p1.traits["email"] = "alice@example.com"
    p1.traits["phone"] = "+254700111222"
    repo.save(p1)

    p2 = BehavioralProfile(identity_id="u2", application_id="app1")
    p2.engagement.tier = "active"
    p2.engagement.sessions_last_30d = 8
    p2.rfm.segment = "loyal"
    p2.rfm.combined_score = 10
    p2.churn.risk_level = "medium"
    p2.traits["is_paying"] = True
    p2.traits["email"] = "bob@example.com"
    repo.save(p2)

    p3 = BehavioralProfile(identity_id="u3", application_id="app1")
    p3.engagement.tier = "cold"
    p3.engagement.sessions_last_30d = 1
    p3.rfm.segment = "at_risk"
    p3.rfm.combined_score = 4
    p3.churn.risk_level = "high"
    p3.traits["is_paying"] = False
    repo.save(p3)


class TestCreateAudience:

    def test_create(self, client):
        resp = client.post("/api/v1/audiences", json={
            "name": "Power Users",
            "description": "Top-tier engaged users",
            "groups": [
                {
                    "operator": "AND",
                    "rules": [
                        {"field": "engagement.tier", "operator": "eq", "value": "power"},
                    ],
                },
            ],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["definition"]["name"] == "Power Users"
        assert data["status"] == "active"
        assert "id" in data

    def test_create_empty_rules(self, client):
        resp = client.post("/api/v1/audiences", json={
            "name": "All Users",
        })
        assert resp.status_code == 200


class TestListAudiences:

    def test_list_empty(self, client):
        resp = client.get("/api/v1/audiences")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_with_audiences(self, client):
        client.post("/api/v1/audiences", json={"name": "A1"})
        client.post("/api/v1/audiences", json={"name": "A2"})
        resp = client.get("/api/v1/audiences")
        assert resp.status_code == 200
        assert len(resp.json()) == 2


class TestGetAudience:

    def test_get(self, client):
        create = client.post("/api/v1/audiences", json={"name": "Test"})
        aid = create.json()["id"]
        resp = client.get(f"/api/v1/audiences/{aid}")
        assert resp.status_code == 200
        assert resp.json()["id"] == aid

    def test_get_not_found(self, client):
        resp = client.get("/api/v1/audiences/nonexistent")
        assert resp.status_code == 404


class TestUpdateAudience:

    def test_update(self, client):
        create = client.post("/api/v1/audiences", json={"name": "Original"})
        aid = create.json()["id"]
        resp = client.put(f"/api/v1/audiences/{aid}", json={
            "name": "Renamed",
            "groups": [
                {
                    "operator": "AND",
                    "rules": [
                        {"field": "churn.risk_level", "operator": "eq", "value": "high"},
                    ],
                },
            ],
        })
        assert resp.status_code == 200
        assert resp.json()["definition"]["name"] == "Renamed"

    def test_update_not_found(self, client):
        resp = client.put("/api/v1/audiences/fake", json={"name": "X"})
        assert resp.status_code == 404


class TestEvaluateAudience:

    def test_evaluate_with_matches(self, client):
        _seed(client)
        create = client.post("/api/v1/audiences", json={
            "name": "Paying",
            "groups": [{
                "operator": "AND",
                "rules": [
                    {"field": "traits.is_paying", "operator": "eq", "value": True},
                ],
            }],
        })
        aid = create.json()["id"]
        resp = client.post(f"/api/v1/audiences/{aid}/evaluate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["matching_count"] == 2
        assert "u1" in data["identity_ids"]
        assert "u2" in data["identity_ids"]

    def test_evaluate_no_matches(self, client):
        _seed(client)
        create = client.post("/api/v1/audiences", json={
            "name": "Nobody",
            "groups": [{
                "operator": "AND",
                "rules": [
                    {"field": "engagement.tier", "operator": "eq", "value": "nonexistent"},
                ],
            }],
        })
        aid = create.json()["id"]
        resp = client.post(f"/api/v1/audiences/{aid}/evaluate")
        assert resp.status_code == 200
        assert resp.json()["matching_count"] == 0

    def test_evaluate_not_found(self, client):
        resp = client.post("/api/v1/audiences/fake/evaluate")
        assert resp.status_code == 404


class TestPreviewAudience:

    def test_preview(self, client):
        _seed(client)
        resp = client.post("/api/v1/audiences/preview", json={
            "name": "preview_test",
            "groups": [{
                "operator": "AND",
                "rules": [
                    {"field": "churn.risk_level", "operator": "eq", "value": "high"},
                ],
            }],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["matching_count"] == 1
        assert "u3" in data["sample_identity_ids"]


class TestExportAudience:

    def test_export_meta(self, client):
        _seed(client)
        create = client.post("/api/v1/audiences", json={
            "name": "Export Test",
            "groups": [{
                "operator": "AND",
                "rules": [
                    {"field": "traits.is_paying", "operator": "eq", "value": True},
                ],
            }],
        })
        aid = create.json()["id"]
        resp = client.post(f"/api/v1/audiences/{aid}/export", json={
            "destination": "meta",
            "config": {"access_token": "tok", "ad_account_id": "act_123"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["records_exported"] == 2
        assert data["destination"] == "meta"

    def test_export_invalid_destination(self, client):
        _seed(client)
        create = client.post("/api/v1/audiences", json={"name": "Bad Dest"})
        aid = create.json()["id"]
        resp = client.post(f"/api/v1/audiences/{aid}/export", json={
            "destination": "snapchat",
            "config": {},
        })
        assert resp.status_code == 400

    def test_export_not_found(self, client):
        resp = client.post("/api/v1/audiences/fake/export", json={
            "destination": "meta",
            "config": {},
        })
        assert resp.status_code == 404


class TestExportJobStatus:

    def test_get_job(self, client):
        _seed(client)
        create = client.post("/api/v1/audiences", json={
            "name": "Job Test",
            "groups": [{
                "operator": "AND",
                "rules": [
                    {"field": "traits.is_paying", "operator": "eq", "value": True},
                ],
            }],
        })
        aid = create.json()["id"]
        export = client.post(f"/api/v1/audiences/{aid}/export", json={
            "destination": "google",
            "config": {},
        })
        job_id = export.json()["id"]
        resp = client.get(f"/api/v1/audiences/exports/{job_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == job_id

    def test_get_job_not_found(self, client):
        resp = client.get("/api/v1/audiences/exports/fake")
        assert resp.status_code == 404


class TestArchiveAudience:

    def test_archive(self, client):
        create = client.post("/api/v1/audiences", json={"name": "To Archive"})
        aid = create.json()["id"]
        resp = client.post(f"/api/v1/audiences/{aid}/archive")
        assert resp.status_code == 200
        assert resp.json()["status"] == "archived"
        listing = client.get("/api/v1/audiences")
        assert len(listing.json()) == 0

    def test_archive_not_found(self, client):
        resp = client.post("/api/v1/audiences/fake/archive")
        assert resp.status_code == 404


class TestEngagementTierRules:

    def test_power_tier(self, client):
        _seed(client)
        create = client.post("/api/v1/audiences", json={
            "name": "Power",
            "groups": [{
                "operator": "AND",
                "rules": [
                    {"field": "engagement.tier", "operator": "eq", "value": "power"},
                ],
            }],
        })
        aid = create.json()["id"]
        resp = client.post(f"/api/v1/audiences/{aid}/evaluate")
        data = resp.json()
        assert data["matching_count"] == 1
        assert "u1" in data["identity_ids"]


class TestRFMSegmentRules:

    def test_champions_segment(self, client):
        _seed(client)
        create = client.post("/api/v1/audiences", json={
            "name": "Champions",
            "groups": [{
                "operator": "AND",
                "rules": [
                    {"field": "rfm.segment", "operator": "eq", "value": "champions"},
                ],
            }],
        })
        aid = create.json()["id"]
        resp = client.post(f"/api/v1/audiences/{aid}/evaluate")
        data = resp.json()
        assert data["matching_count"] == 1
        assert "u1" in data["identity_ids"]


class TestChurnRiskRules:

    def test_high_churn(self, client):
        _seed(client)
        create = client.post("/api/v1/audiences", json={
            "name": "High Churn",
            "groups": [{
                "operator": "AND",
                "rules": [
                    {"field": "churn.risk_level", "operator": "eq", "value": "high"},
                ],
            }],
        })
        aid = create.json()["id"]
        resp = client.post(f"/api/v1/audiences/{aid}/evaluate")
        data = resp.json()
        assert data["matching_count"] == 1
        assert "u3" in data["identity_ids"]


class TestCombinedRuleGroups:

    def test_and_or_combined(self, client):
        _seed(client)
        create = client.post("/api/v1/audiences", json={
            "name": "Engaged OR At Risk",
            "groups": [{
                "operator": "OR",
                "rules": [
                    {"field": "engagement.tier", "operator": "eq", "value": "power"},
                    {"field": "churn.risk_level", "operator": "eq", "value": "high"},
                ],
            }],
        })
        aid = create.json()["id"]
        resp = client.post(f"/api/v1/audiences/{aid}/evaluate")
        data = resp.json()
        assert data["matching_count"] == 2
        assert set(data["identity_ids"]) == {"u1", "u3"}

    def test_multiple_groups_and(self, client):
        _seed(client)
        create = client.post("/api/v1/audiences", json={
            "name": "Paying + Low Churn",
            "groups": [
                {
                    "operator": "AND",
                    "rules": [
                        {"field": "traits.is_paying", "operator": "eq", "value": True},
                    ],
                },
                {
                    "operator": "AND",
                    "rules": [
                        {"field": "churn.risk_level", "operator": "eq", "value": "low"},
                    ],
                },
            ],
        })
        aid = create.json()["id"]
        resp = client.post(f"/api/v1/audiences/{aid}/evaluate")
        data = resp.json()
        assert data["matching_count"] == 1
        assert "u1" in data["identity_ids"]
