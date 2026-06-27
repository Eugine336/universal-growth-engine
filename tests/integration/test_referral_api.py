"""Integration tests for the Referral API."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.rest.app import create_app, pipeline


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture
def platform_client(client):
    resp = client.post(
        "/api/v1/platforms",
        json={
            "name": "Referral Test Platform",
            "slug": "ref-test-plat",
            "owner_email": "test@example.com",
        },
    )
    data = resp.json()
    api_key = data.get("api_key", "")
    platform_id = data.get("platform", {}).get("id", "") if "platform" in data else ""
    return client, api_key, platform_id


class TestReferralProgramAPI:
    def test_create_program(self, client):
        resp = client.post(
            "/api/v1/referrals/programs",
            json={
                "name": "Test Program",
                "referrer_reward_type": "credit",
                "referrer_reward_value": 500,
                "referee_reward_type": "credit",
                "referee_reward_value": 250,
                "reward_currency": "KES",
                "qualification_event": "PAYMENT_COMPLETED",
            },
            params={"platform_id": "integration_test"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Test Program"
        assert data["referrer_reward_value"] == 500
        assert data["reward_currency"] == "KES"

    def test_get_program(self, client):
        client.post(
            "/api/v1/referrals/programs",
            json={"name": "Fetch Test", "referrer_reward_value": 100},
            params={"platform_id": "fetch_plat"},
        )
        resp = client.get(
            "/api/v1/referrals/programs",
            params={"platform_id": "fetch_plat"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Fetch Test"

    def test_get_program_not_found(self, client):
        resp = client.get(
            "/api/v1/referrals/programs",
            params={"platform_id": "nonexistent"},
        )
        assert resp.status_code == 404


class TestReferralCodeAPI:
    def test_generate_code(self, client):
        client.post(
            "/api/v1/referrals/programs",
            json={"name": "Code Test"},
            params={"platform_id": "code_plat"},
        )
        resp = client.post(
            "/api/v1/referrals/codes",
            json={"referrer_identity_id": "identity_001"},
            params={"platform_id": "code_plat"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["referrer_identity_id"] == "identity_001"
        assert len(data["code"]) > 0
        assert data["status"] == "active"

    def test_generate_code_with_entity(self, client):
        client.post(
            "/api/v1/referrals/programs",
            json={"name": "Entity Code Test"},
            params={"platform_id": "entity_plat"},
        )
        resp = client.post(
            "/api/v1/referrals/codes",
            json={
                "referrer_identity_id": "identity_001",
                "referrer_entity_id": "JANE",
            },
            params={"platform_id": "entity_plat"},
        )
        assert resp.status_code == 200
        assert "-" in resp.json()["code"]


class TestReferralRedemptionAPI:
    def test_redeem_code(self, client):
        client.post(
            "/api/v1/referrals/programs",
            json={
                "name": "Redeem Test",
                "referrer_reward_value": 500,
                "referee_reward_value": 250,
                "double_sided": True,
            },
            params={"platform_id": "redeem_plat"},
        )
        code_resp = client.post(
            "/api/v1/referrals/codes",
            json={"referrer_identity_id": "referrer_001"},
            params={"platform_id": "redeem_plat"},
        )
        code_str = code_resp.json()["code"]

        resp = client.post(
            "/api/v1/referrals/redeem",
            json={"code": code_str, "referee_identity_id": "referee_001"},
            params={"platform_id": "redeem_plat"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["referrer_identity_id"] == "referrer_001"
        assert data["referee_identity_id"] == "referee_001"

    def test_redeem_invalid_code(self, client):
        resp = client.post(
            "/api/v1/referrals/redeem",
            json={"code": "FAKE-CODE", "referee_identity_id": "ref_001"},
            params={"platform_id": "redeem_plat"},
        )
        assert resp.status_code == 400

    def test_self_referral_rejected(self, client):
        client.post(
            "/api/v1/referrals/programs",
            json={"name": "Self Test"},
            params={"platform_id": "self_plat"},
        )
        code_resp = client.post(
            "/api/v1/referrals/codes",
            json={"referrer_identity_id": "same_user"},
            params={"platform_id": "self_plat"},
        )
        code_str = code_resp.json()["code"]

        resp = client.post(
            "/api/v1/referrals/redeem",
            json={"code": code_str, "referee_identity_id": "same_user"},
            params={"platform_id": "self_plat"},
        )
        assert resp.status_code == 400


class TestReferralLifecycleAPI:
    def _setup_referral(self, client, platform_id="lifecycle_plat"):
        client.post(
            "/api/v1/referrals/programs",
            json={
                "name": "Lifecycle Test",
                "referrer_reward_value": 500,
                "referee_reward_value": 250,
                "double_sided": True,
                "qualification_event": "PAYMENT_COMPLETED",
            },
            params={"platform_id": platform_id},
        )
        code_resp = client.post(
            "/api/v1/referrals/codes",
            json={"referrer_identity_id": "referrer_001"},
            params={"platform_id": platform_id},
        )
        code_str = code_resp.json()["code"]

        redeem_resp = client.post(
            "/api/v1/referrals/redeem",
            json={"code": code_str, "referee_identity_id": "referee_001"},
            params={"platform_id": platform_id},
        )
        return redeem_resp.json()["id"]

    def test_qualify_referral(self, client):
        referral_id = self._setup_referral(client)
        resp = client.post(f"/api/v1/referrals/{referral_id}/qualify")
        assert resp.status_code == 200
        assert resp.json()["status"] == "qualified"
        assert resp.json()["qualified_at"] is not None

    def test_grant_rewards(self, client):
        referral_id = self._setup_referral(client, "reward_plat")
        client.post(f"/api/v1/referrals/{referral_id}/qualify")
        resp = client.post(f"/api/v1/referrals/{referral_id}/reward")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "rewarded"
        assert data["rewarded_at"] is not None
        assert data["referrer_reward"]["status"] == "granted"
        assert data["referee_reward"]["status"] == "granted"

    def test_reward_before_qualify_fails(self, client):
        referral_id = self._setup_referral(client, "early_reward_plat")
        resp = client.post(f"/api/v1/referrals/{referral_id}/reward")
        assert resp.status_code == 400

    def test_full_lifecycle_api(self, client):
        referral_id = self._setup_referral(client, "full_lifecycle_plat")

        qualify_resp = client.post(f"/api/v1/referrals/{referral_id}/qualify")
        assert qualify_resp.status_code == 200

        reward_resp = client.post(f"/api/v1/referrals/{referral_id}/reward")
        assert reward_resp.status_code == 200
        assert reward_resp.json()["status"] == "rewarded"


class TestReferralStatsAPI:
    def test_get_stats(self, client):
        client.post(
            "/api/v1/referrals/programs",
            json={
                "name": "Stats Test",
                "referrer_reward_value": 100,
                "referee_reward_value": 50,
            },
            params={"platform_id": "stats_plat"},
        )
        code_resp = client.post(
            "/api/v1/referrals/codes",
            json={"referrer_identity_id": "referrer_stats"},
            params={"platform_id": "stats_plat"},
        )
        code_str = code_resp.json()["code"]

        r1 = client.post(
            "/api/v1/referrals/redeem",
            json={"code": code_str, "referee_identity_id": "ref_s1"},
            params={"platform_id": "stats_plat"},
        )
        r2 = client.post(
            "/api/v1/referrals/redeem",
            json={"code": code_str, "referee_identity_id": "ref_s2"},
            params={"platform_id": "stats_plat"},
        )
        r1_id = r1.json()["id"]
        client.post(f"/api/v1/referrals/{r1_id}/qualify")
        client.post(f"/api/v1/referrals/{r1_id}/reward")

        resp = client.get(
            "/api/v1/referrals/stats/referrer_stats",
            params={"platform_id": "stats_plat"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_referrals"] == 2
        assert data["rewarded_count"] == 1
        assert data["total_reward_value"] == 100.0

    def test_list_by_referrer(self, client):
        client.post(
            "/api/v1/referrals/programs",
            json={"name": "List Test"},
            params={"platform_id": "list_plat"},
        )
        code_resp = client.post(
            "/api/v1/referrals/codes",
            json={"referrer_identity_id": "referrer_list"},
            params={"platform_id": "list_plat"},
        )
        code_str = code_resp.json()["code"]
        client.post(
            "/api/v1/referrals/redeem",
            json={"code": code_str, "referee_identity_id": "ref_l1"},
            params={"platform_id": "list_plat"},
        )
        client.post(
            "/api/v1/referrals/redeem",
            json={"code": code_str, "referee_identity_id": "ref_l2"},
            params={"platform_id": "list_plat"},
        )

        resp = client.get(
            "/api/v1/referrals/by-referrer/referrer_list",
            params={"platform_id": "list_plat"},
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 2


class TestCrossPlatformIsolation:
    def test_code_isolated_between_platforms(self, client):
        client.post(
            "/api/v1/referrals/programs",
            json={"name": "Platform A"},
            params={"platform_id": "plat_iso_a"},
        )
        client.post(
            "/api/v1/referrals/programs",
            json={"name": "Platform B"},
            params={"platform_id": "plat_iso_b"},
        )
        code_resp = client.post(
            "/api/v1/referrals/codes",
            json={"referrer_identity_id": "referrer_001"},
            params={"platform_id": "plat_iso_a"},
        )
        code_str = code_resp.json()["code"]

        resp = client.post(
            "/api/v1/referrals/redeem",
            json={"code": code_str, "referee_identity_id": "referee_001"},
            params={"platform_id": "plat_iso_b"},
        )
        assert resp.status_code == 400

    def test_stats_isolated_between_platforms(self, client):
        client.post(
            "/api/v1/referrals/programs",
            json={"name": "Stats Iso A"},
            params={"platform_id": "stats_iso_a"},
        )
        code_resp = client.post(
            "/api/v1/referrals/codes",
            json={"referrer_identity_id": "referrer_iso"},
            params={"platform_id": "stats_iso_a"},
        )
        code_str = code_resp.json()["code"]
        client.post(
            "/api/v1/referrals/redeem",
            json={"code": code_str, "referee_identity_id": "ref_iso_1"},
            params={"platform_id": "stats_iso_a"},
        )

        resp = client.get(
            "/api/v1/referrals/stats/referrer_iso",
            params={"platform_id": "stats_iso_b"},
        )
        assert resp.status_code == 200
        assert resp.json()["total_referrals"] == 0
