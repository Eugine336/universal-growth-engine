"""
Integration tests for cross-platform identity linking REST API.

Full flow: register platforms, enable linking, create shared users,
verify cross-platform discovery, profile aggregation, and promotion candidates.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from api.rest.app import create_app, pipeline


def _slug():
    return f"cp-{uuid.uuid4().hex[:10]}"


@pytest.fixture(scope="module")
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def _register_platform(client, name=None, slug=None):
    name = name or f"Platform-{uuid.uuid4().hex[:6]}"
    slug = slug or _slug()
    resp = client.post("/api/v1/platforms", json={
        "name": name,
        "slug": slug,
        "owner_email": f"{slug}@test.com",
    })
    assert resp.status_code == 200
    data = resp.json()
    return data["id"], data.get("api_key")


# ======================================================================
# Config endpoints
# ======================================================================

class TestCrossPlatformConfig:

    def test_set_config(self, client):
        pid, _ = _register_platform(client)
        resp = client.post("/api/v1/cross-platform/config", json={
            "platform_id": pid,
            "allow_cross_platform_linking": True,
            "share_behavioral_data": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["platform_id"] == pid
        assert data["allow_cross_platform_linking"] is True
        assert data["share_behavioral_data"] is True

    def test_get_config(self, client):
        pid, _ = _register_platform(client)
        client.post("/api/v1/cross-platform/config", json={
            "platform_id": pid,
            "allow_cross_platform_linking": True,
        })
        resp = client.get(f"/api/v1/cross-platform/config?platform_id={pid}")
        assert resp.status_code == 200
        assert resp.json()["allow_cross_platform_linking"] is True

    def test_get_config_not_found(self, client):
        resp = client.get("/api/v1/cross-platform/config?platform_id=nonexistent")
        assert resp.status_code == 404

    def test_update_config(self, client):
        pid, _ = _register_platform(client)
        client.post("/api/v1/cross-platform/config", json={
            "platform_id": pid,
            "allow_cross_platform_linking": False,
        })
        client.post("/api/v1/cross-platform/config", json={
            "platform_id": pid,
            "allow_cross_platform_linking": True,
            "share_behavioral_data": True,
        })
        resp = client.get(f"/api/v1/cross-platform/config?platform_id={pid}")
        assert resp.json()["allow_cross_platform_linking"] is True
        assert resp.json()["share_behavioral_data"] is True

    def test_config_with_partner_whitelist(self, client):
        pid_a, _ = _register_platform(client)
        pid_b, _ = _register_platform(client)
        resp = client.post("/api/v1/cross-platform/config", json={
            "platform_id": pid_a,
            "allow_cross_platform_linking": True,
            "share_behavioral_data": True,
            "allowed_partner_platforms": [pid_b],
        })
        assert resp.status_code == 200
        assert pid_b in resp.json()["allowed_partner_platforms"]


# ======================================================================
# Cross-platform identity discovery
# ======================================================================

class TestCrossPlatformIdentityDiscovery:

    def _create_shared_identity(self, client, pid_a, pid_b, email):
        """Create an identity on two platforms via events."""
        from core.identity.schema import IdentityTouchpoint, TouchpointType

        tp = IdentityTouchpoint(type=TouchpointType.EMAIL, value=email)
        pipeline.identity_resolver.resolve(
            application_id=pid_a, touchpoints=[tp], entity_id=f"e_{pid_a[:4]}"
        )
        pipeline.identity_resolver.resolve(
            application_id=pid_b, touchpoints=[tp], entity_id=f"e_{pid_b[:4]}"
        )

    def test_list_cross_platform_identities(self, client):
        pid_a, _ = _register_platform(client)
        pid_b, _ = _register_platform(client)
        email = f"shared-{uuid.uuid4().hex[:6]}@test.com"
        self._create_shared_identity(client, pid_a, pid_b, email)

        resp = client.get(
            f"/api/v1/cross-platform/identities?platform_id={pid_a}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        found = [d for d in data if pid_b in d["platforms"]]
        assert len(found) >= 1

    def test_no_cross_platform_identities(self, client):
        pid, _ = _register_platform(client)
        resp = client.get(
            f"/api/v1/cross-platform/identities?platform_id={pid}"
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_shared_identities_between_platforms(self, client):
        pid_a, _ = _register_platform(client)
        pid_b, _ = _register_platform(client)
        email = f"shared-{uuid.uuid4().hex[:6]}@test.com"
        self._create_shared_identity(client, pid_a, pid_b, email)

        resp = client.get(
            f"/api/v1/cross-platform/shared/{pid_b}?platform_id={pid_a}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["canonical_email"] == email.lower()

    def test_no_shared_identities(self, client):
        pid_a, _ = _register_platform(client)
        pid_b, _ = _register_platform(client)
        resp = client.get(
            f"/api/v1/cross-platform/shared/{pid_b}?platform_id={pid_a}"
        )
        assert resp.status_code == 200
        assert resp.json() == []


# ======================================================================
# Cross-platform profile
# ======================================================================

class TestCrossPlatformProfile:

    def _create_profiles(self, client, email):
        from core.identity.schema import IdentityTouchpoint, TouchpointType

        pid_a, _ = _register_platform(client)
        pid_b, _ = _register_platform(client)

        tp = IdentityTouchpoint(type=TouchpointType.EMAIL, value=email)
        result = pipeline.identity_resolver.resolve(
            application_id=pid_a, touchpoints=[tp]
        )
        pipeline.identity_resolver.resolve(
            application_id=pid_b, touchpoints=[tp]
        )
        identity_id = result.identity.id

        p1 = pipeline.behavior_repo.get_or_create(identity_id, pid_a)
        p1.engagement.total_sessions = 10
        p1.engagement.tier = "active"
        p1.interests.category_interests = {"tech": 5}
        pipeline.behavior_repo.save(p1)

        p2 = pipeline.behavior_repo.get_or_create(identity_id, pid_b)
        p2.engagement.total_sessions = 15
        p2.engagement.tier = "power"
        p2.interests.category_interests = {"fitness": 8}
        pipeline.behavior_repo.save(p2)

        return pid_a, pid_b, identity_id

    def test_cross_platform_profile_with_sharing(self, client):
        email = f"profile-{uuid.uuid4().hex[:6]}@test.com"
        pid_a, pid_b, identity_id = self._create_profiles(client, email)

        pipeline.cross_platform_manager.set_platform_config(
            __import__("core.identity.cross_platform", fromlist=["CrossPlatformConfig"]).CrossPlatformConfig(
                platform_id=pid_a, share_behavioral_data=True,
            )
        )
        pipeline.cross_platform_manager.set_platform_config(
            __import__("core.identity.cross_platform", fromlist=["CrossPlatformConfig"]).CrossPlatformConfig(
                platform_id=pid_b, share_behavioral_data=True,
            )
        )

        resp = client.get(
            f"/api/v1/cross-platform/identities/{identity_id}/profile"
            f"?platform_id={pid_a}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_sessions"] == 25
        assert data["profile_count"] == 2

    def test_cross_platform_profile_without_sharing(self, client):
        email = f"noshare-{uuid.uuid4().hex[:6]}@test.com"
        pid_a, pid_b, identity_id = self._create_profiles(client, email)

        from core.identity.cross_platform import CrossPlatformConfig
        pipeline.cross_platform_manager.set_platform_config(
            CrossPlatformConfig(platform_id=pid_a, share_behavioral_data=True)
        )

        resp = client.get(
            f"/api/v1/cross-platform/identities/{identity_id}/profile"
            f"?platform_id={pid_a}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_sessions"] == 10
        assert data["profile_count"] == 1

    def test_profile_not_found(self, client):
        resp = client.get(
            "/api/v1/cross-platform/identities/nonexistent/profile"
            "?platform_id=fake"
        )
        assert resp.status_code == 404


# ======================================================================
# Cross-promotion candidates
# ======================================================================

class TestPromotionCandidates:

    def test_candidates_exist(self, client):
        from core.identity.schema import IdentityTouchpoint, TouchpointType

        pid_a, _ = _register_platform(client)
        pid_b, _ = _register_platform(client)

        tp = IdentityTouchpoint(
            type=TouchpointType.EMAIL,
            value=f"only-a-{uuid.uuid4().hex[:6]}@test.com",
        )
        result = pipeline.identity_resolver.resolve(
            application_id=pid_a, touchpoints=[tp]
        )

        p = pipeline.behavior_repo.get_or_create(result.identity.id, pid_a)
        p.engagement.tier = "active"
        pipeline.behavior_repo.save(p)

        resp = client.get(
            f"/api/v1/cross-platform/promotion-candidates/{pid_b}"
            f"?platform_id={pid_a}"
        )
        assert resp.status_code == 200
        data = resp.json()
        found = [c for c in data if c["identity_id"] == result.identity.id]
        assert len(found) == 1
        assert found[0]["engagement_tier"] == "active"

    def test_no_candidates_all_on_target(self, client):
        from core.identity.schema import IdentityTouchpoint, TouchpointType

        pid_a, _ = _register_platform(client)
        pid_b, _ = _register_platform(client)

        tp = IdentityTouchpoint(
            type=TouchpointType.EMAIL,
            value=f"both-{uuid.uuid4().hex[:6]}@test.com",
        )
        result = pipeline.identity_resolver.resolve(
            application_id=pid_a, touchpoints=[tp]
        )
        pipeline.identity_resolver.resolve(
            application_id=pid_b, touchpoints=[tp]
        )

        p = pipeline.behavior_repo.get_or_create(result.identity.id, pid_a)
        p.engagement.tier = "power"
        pipeline.behavior_repo.save(p)

        resp = client.get(
            f"/api/v1/cross-platform/promotion-candidates/{pid_b}"
            f"?platform_id={pid_a}"
        )
        data = resp.json()
        found = [c for c in data if c["identity_id"] == result.identity.id]
        assert len(found) == 0

    def test_candidates_filter_by_engagement(self, client):
        from core.identity.schema import IdentityTouchpoint, TouchpointType

        pid_a, _ = _register_platform(client)
        pid_b, _ = _register_platform(client)

        tp = IdentityTouchpoint(
            type=TouchpointType.EMAIL,
            value=f"cold-{uuid.uuid4().hex[:6]}@test.com",
        )
        result = pipeline.identity_resolver.resolve(
            application_id=pid_a, touchpoints=[tp]
        )

        p = pipeline.behavior_repo.get_or_create(result.identity.id, pid_a)
        p.engagement.tier = "cold"
        pipeline.behavior_repo.save(p)

        resp = client.get(
            f"/api/v1/cross-platform/promotion-candidates/{pid_b}"
            f"?platform_id={pid_a}&min_engagement_tier=active"
        )
        data = resp.json()
        found = [c for c in data if c["identity_id"] == result.identity.id]
        assert len(found) == 0


# ======================================================================
# Stats
# ======================================================================

class TestCrossPlatformStats:

    def test_stats_endpoint(self, client):
        resp = client.get("/api/v1/cross-platform/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_configs" in data
        assert "total_links" in data
        assert "unique_linked_identities" in data


# ======================================================================
# Full flow
# ======================================================================

class TestFullCrossPlatformFlow:

    def test_end_to_end_cross_platform_linking(self, client):
        from core.identity.schema import IdentityTouchpoint, TouchpointType
        from core.identity.cross_platform import CrossPlatformConfig

        pid_a, _ = _register_platform(client, name="UCMC", slug=_slug())
        pid_b, _ = _register_platform(client, name="FitNaija", slug=_slug())

        client.post("/api/v1/cross-platform/config", json={
            "platform_id": pid_a,
            "allow_cross_platform_linking": True,
            "share_behavioral_data": True,
        })
        client.post("/api/v1/cross-platform/config", json={
            "platform_id": pid_b,
            "allow_cross_platform_linking": True,
            "share_behavioral_data": True,
        })

        email = f"amaka-{uuid.uuid4().hex[:6]}@gmail.com"
        tp = IdentityTouchpoint(type=TouchpointType.EMAIL, value=email)

        r1 = pipeline.identity_resolver.resolve(
            application_id=pid_a, touchpoints=[tp], entity_id="seller_001"
        )
        identity_id = r1.identity.id

        r2 = pipeline.identity_resolver.resolve_cross_platform(
            platform_id=pid_b, touchpoints=[tp], entity_id="member_001"
        )
        assert r2.identity.id == identity_id

        p_a = pipeline.behavior_repo.get_or_create(identity_id, pid_a)
        p_a.engagement.total_sessions = 28
        p_a.engagement.tier = "power"
        p_a.rfm.total_conversions = 20
        p_a.rfm.total_monetary_value = 150000.0
        p_a.interests.category_interests = {"ai_education": 15, "tech": 10}
        pipeline.behavior_repo.save(p_a)

        p_b = pipeline.behavior_repo.get_or_create(identity_id, pid_b)
        p_b.engagement.total_sessions = 5
        p_b.engagement.tier = "warming"
        p_b.interests.category_interests = {"fitness": 8}
        pipeline.behavior_repo.save(p_b)

        resp = client.get(
            f"/api/v1/cross-platform/identities/{identity_id}/profile"
            f"?platform_id={pid_a}"
        )
        assert resp.status_code == 200
        profile = resp.json()
        assert profile["total_sessions"] == 33
        assert profile["highest_engagement_tier"] == "power"
        assert profile["combined_interests"]["ai_education"] == 15
        assert profile["combined_interests"]["fitness"] == 8
        assert profile["profile_count"] == 2

        resp = client.get(
            f"/api/v1/cross-platform/shared/{pid_b}?platform_id={pid_a}"
        )
        assert resp.status_code == 200
        shared = resp.json()
        assert any(s["identity_id"] == identity_id for s in shared)

        resp = client.get("/api/v1/cross-platform/stats")
        assert resp.status_code == 200

    def test_partner_whitelist_enforcement(self, client):
        from core.identity.schema import IdentityTouchpoint, TouchpointType

        pid_a, _ = _register_platform(client, slug=_slug())
        pid_b, _ = _register_platform(client, slug=_slug())
        pid_c, _ = _register_platform(client, slug=_slug())

        client.post("/api/v1/cross-platform/config", json={
            "platform_id": pid_a,
            "allow_cross_platform_linking": True,
            "share_behavioral_data": True,
            "allowed_partner_platforms": [pid_b],
        })

        email = f"whitelist-{uuid.uuid4().hex[:6]}@test.com"
        tp = IdentityTouchpoint(type=TouchpointType.EMAIL, value=email)
        result = pipeline.identity_resolver.resolve(
            application_id=pid_a, touchpoints=[tp]
        )
        identity_id = result.identity.id

        p = pipeline.behavior_repo.get_or_create(identity_id, pid_a)
        p.engagement.total_sessions = 10
        p.engagement.tier = "active"
        pipeline.behavior_repo.save(p)

        resp_b = client.get(
            f"/api/v1/cross-platform/identities/{identity_id}/profile"
            f"?platform_id={pid_b}"
        )
        assert resp_b.status_code == 200
        assert resp_b.json()["total_sessions"] == 10

        resp_c = client.get(
            f"/api/v1/cross-platform/identities/{identity_id}/profile"
            f"?platform_id={pid_c}"
        )
        assert resp_c.status_code == 404
