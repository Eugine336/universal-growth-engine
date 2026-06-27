"""
Unit tests for cross-platform identity linking.

Tests CrossPlatformConfig, CrossPlatformLink, CrossPlatformManager,
and resolve_cross_platform on IdentityResolver.
"""

import hashlib

import pytest

from core.behavior.repository import BehaviorRepository
from core.behavior.schema import BehavioralProfile, EngagementProfile, InterestProfile, RFMScore
from core.identity.cross_platform import (
    CrossPlatformConfig,
    CrossPlatformLink,
    CrossPlatformManager,
)
from core.identity.graph import IdentityGraph
from core.identity.resolver import IdentityResolver
from core.identity.schema import Identity, IdentityTouchpoint, TouchpointType


# ======================================================================
# CrossPlatformConfig
# ======================================================================

class TestCrossPlatformConfig:

    def test_create_default(self):
        config = CrossPlatformConfig(platform_id="ucmc")
        assert config.platform_id == "ucmc"
        assert config.allow_cross_platform_linking is False
        assert config.share_behavioral_data is False
        assert config.allowed_partner_platforms == []
        assert config.linkable_touchpoint_types == ["email", "phone"]

    def test_create_enabled(self):
        config = CrossPlatformConfig(
            platform_id="ucmc",
            allow_cross_platform_linking=True,
            share_behavioral_data=True,
            allowed_partner_platforms=["fitnaija"],
        )
        assert config.allow_cross_platform_linking is True
        assert config.share_behavioral_data is True
        assert config.allowed_partner_platforms == ["fitnaija"]

    def test_custom_linkable_types(self):
        config = CrossPlatformConfig(
            platform_id="ucmc",
            linkable_touchpoint_types=["email", "phone", "device_id"],
        )
        assert "device_id" in config.linkable_touchpoint_types


# ======================================================================
# CrossPlatformLink
# ======================================================================

class TestCrossPlatformLink:

    def test_create_link(self):
        link = CrossPlatformLink(
            identity_id="id-1",
            platform_ids=["ucmc", "fitnaija"],
            link_type="email",
            link_value_hash=hashlib.sha256(b"test@email.com").hexdigest(),
        )
        assert link.identity_id == "id-1"
        assert link.platform_ids == ["ucmc", "fitnaija"]
        assert link.link_type == "email"
        assert link.consent_status == "auto"
        assert link.id  # auto-generated UUID

    def test_link_value_is_hash_not_raw(self):
        raw = "user@example.com"
        hashed = hashlib.sha256(raw.encode()).hexdigest()
        link = CrossPlatformLink(
            identity_id="id-1",
            platform_ids=["a", "b"],
            link_type="email",
            link_value_hash=hashed,
        )
        assert link.link_value_hash == hashed
        assert raw not in link.link_value_hash


# ======================================================================
# CrossPlatformManager — Config
# ======================================================================

class TestManagerConfig:

    def _make_manager(self):
        graph = IdentityGraph()
        repo = BehaviorRepository()
        return CrossPlatformManager(graph, repo)

    def test_set_and_get_config(self):
        mgr = self._make_manager()
        config = CrossPlatformConfig(
            platform_id="ucmc",
            allow_cross_platform_linking=True,
        )
        result = mgr.set_platform_config(config)
        assert result.platform_id == "ucmc"

        fetched = mgr.get_platform_config("ucmc")
        assert fetched is not None
        assert fetched.allow_cross_platform_linking is True

    def test_get_config_nonexistent(self):
        mgr = self._make_manager()
        assert mgr.get_platform_config("nope") is None

    def test_is_linking_enabled(self):
        mgr = self._make_manager()
        assert mgr.is_linking_enabled("ucmc") is False

        mgr.set_platform_config(CrossPlatformConfig(
            platform_id="ucmc", allow_cross_platform_linking=True,
        ))
        assert mgr.is_linking_enabled("ucmc") is True


# ======================================================================
# CrossPlatformManager — Consent checks
# ======================================================================

class TestSharingAllowed:

    def _make_manager(self):
        graph = IdentityGraph()
        repo = BehaviorRepository()
        return CrossPlatformManager(graph, repo)

    def test_same_platform_always_allowed(self):
        mgr = self._make_manager()
        assert mgr._check_sharing_allowed("ucmc", "ucmc") is True

    def test_sharing_disabled(self):
        mgr = self._make_manager()
        mgr.set_platform_config(CrossPlatformConfig(
            platform_id="ucmc", share_behavioral_data=False,
        ))
        assert mgr._check_sharing_allowed("ucmc", "fitnaija") is False

    def test_sharing_enabled_no_whitelist(self):
        mgr = self._make_manager()
        mgr.set_platform_config(CrossPlatformConfig(
            platform_id="ucmc",
            share_behavioral_data=True,
            allowed_partner_platforms=[],
        ))
        assert mgr._check_sharing_allowed("ucmc", "fitnaija") is True

    def test_sharing_enabled_with_whitelist_match(self):
        mgr = self._make_manager()
        mgr.set_platform_config(CrossPlatformConfig(
            platform_id="ucmc",
            share_behavioral_data=True,
            allowed_partner_platforms=["fitnaija"],
        ))
        assert mgr._check_sharing_allowed("ucmc", "fitnaija") is True

    def test_sharing_enabled_with_whitelist_no_match(self):
        mgr = self._make_manager()
        mgr.set_platform_config(CrossPlatformConfig(
            platform_id="ucmc",
            share_behavioral_data=True,
            allowed_partner_platforms=["fitnaija"],
        ))
        assert mgr._check_sharing_allowed("ucmc", "other") is False

    def test_no_config_means_no_sharing(self):
        mgr = self._make_manager()
        assert mgr._check_sharing_allowed("ucmc", "fitnaija") is False


# ======================================================================
# CrossPlatformManager — Identity discovery
# ======================================================================

class TestIdentityDiscovery:

    def _setup(self):
        graph = IdentityGraph()
        repo = BehaviorRepository()
        mgr = CrossPlatformManager(graph, repo)
        resolver = IdentityResolver(graph)
        return graph, repo, mgr, resolver

    def test_find_cross_platform_identities(self):
        graph, repo, mgr, resolver = self._setup()

        tp_email = IdentityTouchpoint(type=TouchpointType.EMAIL, value="shared@test.com")
        resolver.resolve(application_id="ucmc", touchpoints=[tp_email], entity_id="buyer_1")
        resolver.resolve(application_id="fitnaija", touchpoints=[tp_email], entity_id="member_1")

        results = mgr.find_cross_platform_identities("ucmc")
        assert len(results) == 1
        assert "fitnaija" in results[0]["platforms"]
        assert "ucmc" in results[0]["platforms"]

    def test_find_cross_platform_no_overlap(self):
        graph, repo, mgr, resolver = self._setup()

        tp1 = IdentityTouchpoint(type=TouchpointType.EMAIL, value="user1@test.com")
        tp2 = IdentityTouchpoint(type=TouchpointType.EMAIL, value="user2@test.com")
        resolver.resolve(application_id="ucmc", touchpoints=[tp1])
        resolver.resolve(application_id="fitnaija", touchpoints=[tp2])

        results = mgr.find_cross_platform_identities("ucmc")
        assert len(results) == 0

    def test_get_shared_identities(self):
        graph, repo, mgr, resolver = self._setup()

        tp = IdentityTouchpoint(type=TouchpointType.EMAIL, value="both@test.com")
        resolver.resolve(application_id="platform_a", touchpoints=[tp])
        resolver.resolve(application_id="platform_b", touchpoints=[tp])

        shared = mgr.get_shared_identities("platform_a", "platform_b")
        assert len(shared) == 1

    def test_get_shared_identities_none(self):
        graph, repo, mgr, resolver = self._setup()

        tp1 = IdentityTouchpoint(type=TouchpointType.EMAIL, value="a@test.com")
        tp2 = IdentityTouchpoint(type=TouchpointType.EMAIL, value="b@test.com")
        resolver.resolve(application_id="platform_a", touchpoints=[tp1])
        resolver.resolve(application_id="platform_b", touchpoints=[tp2])

        shared = mgr.get_shared_identities("platform_a", "platform_b")
        assert len(shared) == 0


# ======================================================================
# CrossPlatformManager — Profile aggregation
# ======================================================================

class TestProfileAggregation:

    def _setup_with_profiles(self):
        graph = IdentityGraph()
        repo = BehaviorRepository()
        mgr = CrossPlatformManager(graph, repo)
        resolver = IdentityResolver(graph)

        tp = IdentityTouchpoint(type=TouchpointType.EMAIL, value="user@test.com")
        result = resolver.resolve(application_id="ucmc", touchpoints=[tp])
        resolver.resolve(application_id="fitnaija", touchpoints=[tp])
        identity_id = result.identity.id

        p1 = repo.get_or_create(identity_id, "ucmc")
        p1.engagement.total_sessions = 20
        p1.engagement.total_events = 100
        p1.engagement.tier = "active"
        p1.interests.category_interests = {"tech": 10, "education": 5}
        p1.rfm.total_conversions = 3
        p1.rfm.total_monetary_value = 1500.0
        repo.save(p1)

        p2 = repo.get_or_create(identity_id, "fitnaija")
        p2.engagement.total_sessions = 30
        p2.engagement.total_events = 200
        p2.engagement.tier = "power"
        p2.interests.category_interests = {"fitness": 15, "tech": 3}
        p2.rfm.total_conversions = 5
        p2.rfm.total_monetary_value = 2500.0
        repo.save(p2)

        return graph, repo, mgr, identity_id

    def test_merge_profiles_aggregates_sessions(self):
        _, repo, mgr, identity_id = self._setup_with_profiles()

        mgr.set_platform_config(CrossPlatformConfig(
            platform_id="ucmc", share_behavioral_data=True,
        ))
        mgr.set_platform_config(CrossPlatformConfig(
            platform_id="fitnaija", share_behavioral_data=True,
        ))

        profile = mgr.get_cross_platform_profile(identity_id, "ucmc")
        assert profile is not None
        assert profile["total_sessions"] == 50
        assert profile["total_events"] == 300

    def test_merge_profiles_aggregates_conversions(self):
        _, _, mgr, identity_id = self._setup_with_profiles()

        mgr.set_platform_config(CrossPlatformConfig(
            platform_id="ucmc", share_behavioral_data=True,
        ))
        mgr.set_platform_config(CrossPlatformConfig(
            platform_id="fitnaija", share_behavioral_data=True,
        ))

        profile = mgr.get_cross_platform_profile(identity_id, "ucmc")
        assert profile["total_conversions"] == 8
        assert profile["total_monetary_value"] == 4000.0

    def test_merge_profiles_combines_interests(self):
        _, _, mgr, identity_id = self._setup_with_profiles()

        mgr.set_platform_config(CrossPlatformConfig(
            platform_id="ucmc", share_behavioral_data=True,
        ))
        mgr.set_platform_config(CrossPlatformConfig(
            platform_id="fitnaija", share_behavioral_data=True,
        ))

        profile = mgr.get_cross_platform_profile(identity_id, "ucmc")
        assert profile["combined_interests"]["tech"] == 13
        assert profile["combined_interests"]["fitness"] == 15
        assert profile["combined_interests"]["education"] == 5

    def test_merge_profiles_picks_highest_tier(self):
        _, _, mgr, identity_id = self._setup_with_profiles()

        mgr.set_platform_config(CrossPlatformConfig(
            platform_id="ucmc", share_behavioral_data=True,
        ))
        mgr.set_platform_config(CrossPlatformConfig(
            platform_id="fitnaija", share_behavioral_data=True,
        ))

        profile = mgr.get_cross_platform_profile(identity_id, "ucmc")
        assert profile["highest_engagement_tier"] == "power"

    def test_merge_profiles_respects_sharing_permissions(self):
        _, _, mgr, identity_id = self._setup_with_profiles()

        mgr.set_platform_config(CrossPlatformConfig(
            platform_id="ucmc", share_behavioral_data=True,
        ))
        # fitnaija does NOT share
        mgr.set_platform_config(CrossPlatformConfig(
            platform_id="fitnaija", share_behavioral_data=False,
        ))

        profile = mgr.get_cross_platform_profile(identity_id, "ucmc")
        assert profile["total_sessions"] == 20
        assert profile["profile_count"] == 1

    def test_profile_nonexistent_identity(self):
        graph = IdentityGraph()
        repo = BehaviorRepository()
        mgr = CrossPlatformManager(graph, repo)
        assert mgr.get_cross_platform_profile("nonexistent", "ucmc") is None


# ======================================================================
# CrossPlatformManager — Cross-promotion candidates
# ======================================================================

class TestCrossPromotionCandidates:

    def _setup(self):
        graph = IdentityGraph()
        repo = BehaviorRepository()
        mgr = CrossPlatformManager(graph, repo)
        resolver = IdentityResolver(graph)
        return graph, repo, mgr, resolver

    def test_candidates_excludes_users_already_on_target(self):
        graph, repo, mgr, resolver = self._setup()

        tp = IdentityTouchpoint(type=TouchpointType.EMAIL, value="shared@test.com")
        result = resolver.resolve(application_id="ucmc", touchpoints=[tp])
        resolver.resolve(application_id="fitnaija", touchpoints=[tp])

        p = repo.get_or_create(result.identity.id, "ucmc")
        p.engagement.tier = "active"
        repo.save(p)

        candidates = mgr.get_cross_promotion_candidates("ucmc", "fitnaija")
        assert len(candidates) == 0

    def test_candidates_returns_eligible_users(self):
        graph, repo, mgr, resolver = self._setup()

        tp = IdentityTouchpoint(type=TouchpointType.EMAIL, value="only_ucmc@test.com")
        result = resolver.resolve(application_id="ucmc", touchpoints=[tp])

        p = repo.get_or_create(result.identity.id, "ucmc")
        p.engagement.tier = "active"
        repo.save(p)

        candidates = mgr.get_cross_promotion_candidates("ucmc", "fitnaija")
        assert len(candidates) == 1
        assert candidates[0]["identity_id"] == result.identity.id
        assert candidates[0]["engagement_tier"] == "active"

    def test_candidates_filters_by_tier(self):
        graph, repo, mgr, resolver = self._setup()

        tp = IdentityTouchpoint(type=TouchpointType.EMAIL, value="cold@test.com")
        result = resolver.resolve(application_id="ucmc", touchpoints=[tp])

        p = repo.get_or_create(result.identity.id, "ucmc")
        p.engagement.tier = "cold"
        repo.save(p)

        candidates = mgr.get_cross_promotion_candidates(
            "ucmc", "fitnaija", min_engagement_tier="warming"
        )
        assert len(candidates) == 0

    def test_candidates_email_hidden_when_no_sharing(self):
        graph, repo, mgr, resolver = self._setup()

        tp = IdentityTouchpoint(type=TouchpointType.EMAIL, value="user@test.com")
        result = resolver.resolve(application_id="ucmc", touchpoints=[tp])

        p = repo.get_or_create(result.identity.id, "ucmc")
        p.engagement.tier = "power"
        repo.save(p)

        candidates = mgr.get_cross_promotion_candidates("ucmc", "fitnaija")
        assert candidates[0]["canonical_email"] is None

    def test_candidates_email_visible_when_sharing(self):
        graph, repo, mgr, resolver = self._setup()

        mgr.set_platform_config(CrossPlatformConfig(
            platform_id="ucmc", share_behavioral_data=True,
        ))

        tp = IdentityTouchpoint(type=TouchpointType.EMAIL, value="user@test.com")
        result = resolver.resolve(application_id="ucmc", touchpoints=[tp])

        p = repo.get_or_create(result.identity.id, "ucmc")
        p.engagement.tier = "power"
        repo.save(p)

        candidates = mgr.get_cross_promotion_candidates("ucmc", "fitnaija")
        assert candidates[0]["canonical_email"] == "user@test.com"


# ======================================================================
# CrossPlatformManager — Link management
# ======================================================================

class TestLinkManagement:

    def _make_manager(self):
        graph = IdentityGraph()
        repo = BehaviorRepository()
        return CrossPlatformManager(graph, repo)

    def test_record_link(self):
        mgr = self._make_manager()
        link = mgr.record_link(
            identity_id="id-1",
            platform_ids=["ucmc", "fitnaija"],
            link_type="email",
            link_value="user@test.com",
        )
        assert link.identity_id == "id-1"
        assert link.link_type == "email"
        assert link.link_value_hash == hashlib.sha256(b"user@test.com").hexdigest()

    def test_get_links_for_identity(self):
        mgr = self._make_manager()
        mgr.record_link("id-1", ["ucmc", "fitnaija"], "email", "user@test.com")
        links = mgr.get_links_for_identity("id-1")
        assert len(links) == 1

    def test_get_links_empty(self):
        mgr = self._make_manager()
        links = mgr.get_links_for_identity("nonexistent")
        assert links == []

    def test_hash_value_privacy(self):
        mgr = self._make_manager()
        link = mgr.record_link("id-1", ["a", "b"], "email", "User@Test.COM")
        expected = hashlib.sha256(b"user@test.com").hexdigest()
        assert link.link_value_hash == expected


# ======================================================================
# CrossPlatformManager — Stats
# ======================================================================

class TestStats:

    def _make_manager(self):
        graph = IdentityGraph()
        repo = BehaviorRepository()
        return CrossPlatformManager(graph, repo)

    def test_empty_stats(self):
        mgr = self._make_manager()
        stats = mgr.stats()
        assert stats["total_configs"] == 0
        assert stats["total_links"] == 0
        assert stats["unique_linked_identities"] == 0

    def test_stats_after_config_and_links(self):
        mgr = self._make_manager()
        mgr.set_platform_config(CrossPlatformConfig(
            platform_id="ucmc", allow_cross_platform_linking=True,
            share_behavioral_data=True,
        ))
        mgr.set_platform_config(CrossPlatformConfig(
            platform_id="fitnaija", allow_cross_platform_linking=False,
        ))
        mgr.record_link("id-1", ["ucmc", "fitnaija"], "email", "u@t.com")
        mgr.record_link("id-2", ["ucmc", "fitnaija"], "email", "v@t.com")

        stats = mgr.stats()
        assert stats["total_configs"] == 2
        assert stats["linking_enabled_platforms"] == 1
        assert stats["sharing_enabled_platforms"] == 1
        assert stats["total_links"] == 2
        assert stats["unique_linked_identities"] == 2


# ======================================================================
# IdentityResolver — resolve_cross_platform
# ======================================================================

class TestResolveCrossPlatform:

    def _setup(self):
        graph = IdentityGraph()
        repo = BehaviorRepository()
        mgr = CrossPlatformManager(graph, repo)
        resolver = IdentityResolver(graph, mgr)
        return graph, repo, mgr, resolver

    def test_linking_disabled_creates_separate_identity(self):
        graph, repo, mgr, resolver = self._setup()

        tp = IdentityTouchpoint(type=TouchpointType.EMAIL, value="user@test.com")
        r1 = resolver.resolve(application_id="ucmc", touchpoints=[tp])

        mgr.set_platform_config(CrossPlatformConfig(
            platform_id="fitnaija", allow_cross_platform_linking=False,
        ))
        r2 = resolver.resolve_cross_platform(
            platform_id="fitnaija", touchpoints=[tp]
        )
        assert r2.identity.id == r1.identity.id

    def test_linking_enabled_creates_link_on_shared_identity(self):
        graph, repo, mgr, resolver = self._setup()

        mgr.set_platform_config(CrossPlatformConfig(
            platform_id="ucmc", allow_cross_platform_linking=True,
        ))
        mgr.set_platform_config(CrossPlatformConfig(
            platform_id="fitnaija", allow_cross_platform_linking=True,
        ))

        tp = IdentityTouchpoint(type=TouchpointType.EMAIL, value="cross@test.com")
        r1 = resolver.resolve(application_id="ucmc", touchpoints=[tp])
        r2 = resolver.resolve_cross_platform(
            platform_id="fitnaija", touchpoints=[tp]
        )

        assert r2.identity.id == r1.identity.id
        assert "ucmc" in r2.identity.application_ids
        assert "fitnaija" in r2.identity.application_ids

        links = mgr.get_links_for_identity(r2.identity.id)
        assert len(links) == 1
        assert links[0].link_type == "email"

    def test_resolve_cross_platform_with_no_manager(self):
        graph = IdentityGraph()
        resolver = IdentityResolver(graph, cross_platform_manager=None)

        tp = IdentityTouchpoint(type=TouchpointType.EMAIL, value="no_mgr@test.com")
        result = resolver.resolve_cross_platform(
            platform_id="ucmc", touchpoints=[tp]
        )
        assert result.created is True

    def test_resolve_cross_platform_new_identity_no_link(self):
        graph, repo, mgr, resolver = self._setup()

        mgr.set_platform_config(CrossPlatformConfig(
            platform_id="ucmc", allow_cross_platform_linking=True,
        ))

        tp = IdentityTouchpoint(type=TouchpointType.EMAIL, value="new@test.com")
        result = resolver.resolve_cross_platform(
            platform_id="ucmc", touchpoints=[tp]
        )

        assert result.created is True
        links = mgr.get_links_for_identity(result.identity.id)
        assert len(links) == 0
