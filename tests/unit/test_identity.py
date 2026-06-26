"""
Unit Tests — core/identity

Tests cover:
- Identity schema and touchpoint management
- IdentityGraph CRUD and indexing
- IdentityMerger merge logic
- IdentityResolver resolution, creation, and merge triggering
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest
from datetime import datetime, timezone, timedelta

from core.identity.schema import (
    Identity, IdentityTouchpoint, TouchpointType, IdentityStatus
)
from core.identity.graph import IdentityGraph
from core.identity.merger import IdentityMerger
from core.identity.resolver import IdentityResolver
from core.events.schema import Event, EventType, EventContext, DeviceContext


# ===========================================================================
# Fixtures
# ===========================================================================

def make_tp(type: TouchpointType, value: str, **kwargs) -> IdentityTouchpoint:
    return IdentityTouchpoint(type=type, value=value, **kwargs)

def email_tp(email: str) -> IdentityTouchpoint:
    return make_tp(TouchpointType.EMAIL, email)

def device_tp(device_id: str) -> IdentityTouchpoint:
    return make_tp(TouchpointType.DEVICE_ID, device_id)

def make_identity(*touchpoints) -> Identity:
    identity = Identity()
    for tp in touchpoints:
        identity.add_touchpoint(tp)
    return identity

def make_graph() -> IdentityGraph:
    return IdentityGraph()

def make_resolver() -> IdentityResolver:
    return IdentityResolver(make_graph())


# ===========================================================================
# Identity Schema Tests
# ===========================================================================

class TestIdentitySchema:

    def test_identity_created_with_defaults(self):
        identity = Identity()
        assert identity.id is not None
        assert identity.status == IdentityStatus.ANONYMOUS
        assert identity.touchpoints == []

    def test_add_email_touchpoint_sets_canonical(self):
        identity = Identity()
        identity.add_touchpoint(email_tp("user@example.com"))
        assert identity.canonical_email == "user@example.com"

    def test_add_phone_sets_canonical(self):
        identity = Identity()
        identity.add_touchpoint(make_tp(TouchpointType.PHONE, "+254700000000"))
        assert identity.canonical_phone == "+254700000000"

    def test_adding_email_promotes_status_from_anonymous(self):
        identity = Identity()
        assert identity.is_anonymous()
        identity.add_touchpoint(email_tp("user@example.com"))
        assert identity.status == IdentityStatus.ACTIVE

    def test_anonymous_touchpoint_keeps_status_anonymous(self):
        identity = Identity()
        identity.add_touchpoint(make_tp(TouchpointType.ANONYMOUS, "anon_abc"))
        assert identity.is_anonymous()

    def test_duplicate_touchpoint_not_added_twice(self):
        identity = Identity()
        identity.add_touchpoint(email_tp("user@example.com"))
        identity.add_touchpoint(email_tp("user@example.com"))
        assert len(identity.touchpoints) == 1

    def test_touchpoint_key_is_lowercase(self):
        tp = email_tp("User@Example.COM")
        assert tp.key() == "email:user@example.com"

    def test_register_entity(self):
        identity = Identity()
        identity.register_entity("ucmc", "buyer_001")
        assert identity.entity_ids["ucmc"] == "buyer_001"
        assert "ucmc" in identity.application_ids

    def test_set_trait(self):
        identity = Identity()
        identity.set_trait("country", "KE")
        assert identity.traits["country"] == "KE"

    def test_touchpoint_keys_list(self):
        identity = make_identity(
            email_tp("a@b.com"),
            device_tp("device_001"),
        )
        keys = identity.touchpoint_keys()
        assert "email:a@b.com" in keys
        assert "device_id:device_001" in keys


# ===========================================================================
# Identity Graph Tests
# ===========================================================================

class TestIdentityGraph:

    def setup_method(self):
        self.graph = make_graph()

    def test_save_and_get(self):
        identity = make_identity(email_tp("a@b.com"))
        self.graph.save(identity)
        fetched = self.graph.get(identity.id)
        assert fetched is not None
        assert fetched.id == identity.id

    def test_find_by_touchpoint(self):
        identity = make_identity(email_tp("a@b.com"))
        self.graph.save(identity)
        tp = email_tp("a@b.com")
        found = self.graph.find_by_touchpoint(tp)
        assert found is not None
        assert found.id == identity.id

    def test_find_by_email(self):
        identity = make_identity(email_tp("hello@test.com"))
        self.graph.save(identity)
        found = self.graph.find_by_email("hello@test.com")
        assert found.id == identity.id

    def test_find_by_device(self):
        identity = make_identity(device_tp("device_xyz"))
        self.graph.save(identity)
        found = self.graph.find_by_device("device_xyz")
        assert found.id == identity.id

    def test_find_by_entity(self):
        identity = make_identity(email_tp("e@f.com"))
        identity.register_entity("ucmc", "buyer_99")
        self.graph.save(identity)
        found = self.graph.find_by_entity("ucmc", "buyer_99")
        assert found.id == identity.id

    def test_not_found_returns_none(self):
        assert self.graph.get("nonexistent_id") is None
        assert self.graph.find_by_email("nobody@nowhere.com") is None

    def test_delete_removes_identity_and_indexes(self):
        identity = make_identity(email_tp("del@test.com"))
        self.graph.save(identity)
        self.graph.delete(identity.id)
        assert self.graph.get(identity.id) is None
        assert self.graph.find_by_email("del@test.com") is None

    def test_list_by_application(self):
        i1 = make_identity(email_tp("a@b.com"))
        i1.touch("ucmc")
        i2 = make_identity(email_tp("c@d.com"))
        i2.touch("trading")
        self.graph.save(i1)
        self.graph.save(i2)
        ucmc_ids = self.graph.list_by_application("ucmc")
        assert len(ucmc_ids) == 1
        assert ucmc_ids[0].id == i1.id

    def test_stats(self):
        i1 = make_identity(email_tp("a@b.com"))
        i2 = Identity()  # anonymous
        self.graph.save(i1)
        self.graph.save(i2)
        stats = self.graph.stats()
        assert stats["total_identities"] == 2
        assert stats["anonymous"] == 1


# ===========================================================================
# Identity Merger Tests
# ===========================================================================

class TestIdentityMerger:

    def setup_method(self):
        self.graph = make_graph()
        self.merger = IdentityMerger(self.graph)

    def _save(self, *touchpoints) -> Identity:
        identity = make_identity(*touchpoints)
        self.graph.save(identity)
        return identity

    def test_basic_merge(self):
        a = self._save(email_tp("a@b.com"))
        b = self._save(device_tp("device_001"))
        result = self.merger.merge(a.id, b.id)
        assert result is not None
        assert result.canonical.id in {a.id, b.id}
        assert result.absorbed.is_merged()

    def test_merged_identity_points_to_canonical(self):
        a = self._save(email_tp("a@b.com"))
        b = self._save(device_tp("device_001"))
        result = self.merger.merge(a.id, b.id)
        assert result.absorbed.merged_into == result.canonical.id

    def test_touchpoints_combined_after_merge(self):
        a = self._save(email_tp("a@b.com"))
        b = self._save(device_tp("device_001"))
        result = self.merger.merge(a.id, b.id)
        keys = result.canonical.touchpoint_keys()
        assert "email:a@b.com" in keys
        assert "device_id:device_001" in keys

    def test_traits_merged(self):
        a = self._save(email_tp("a@b.com"))
        a.set_trait("country", "KE")
        self.graph.save(a)

        b = self._save(device_tp("device_001"))
        b.set_trait("language", "sw")
        self.graph.save(b)

        result = self.merger.merge(a.id, b.id)
        assert result.canonical.traits.get("country") == "KE"
        assert result.canonical.traits.get("language") == "sw"

    def test_merge_same_identity_skipped(self):
        a = self._save(email_tp("a@b.com"))
        result = self.merger.merge(a.id, a.id)
        assert result is None

    def test_merge_already_merged_identity_skipped(self):
        a = self._save(email_tp("a@b.com"))
        b = self._save(device_tp("d1"))
        c = self._save(device_tp("d2"))
        self.merger.merge(a.id, b.id)
        # b is now merged — trying to merge b again should be skipped
        result = self.merger.merge(b.id, c.id)
        assert result is None

    def test_entity_mappings_merged(self):
        a = self._save(email_tp("a@b.com"))
        a.register_entity("ucmc", "buyer_01")
        self.graph.save(a)

        b = self._save(device_tp("d1"))
        b.register_entity("trading", "trader_01")
        self.graph.save(b)

        result = self.merger.merge(a.id, b.id)
        assert "ucmc" in result.canonical.entity_ids
        assert "trading" in result.canonical.entity_ids


# ===========================================================================
# Identity Resolver Tests
# ===========================================================================

class TestIdentityResolver:

    def setup_method(self):
        self.graph = make_graph()
        self.resolver = IdentityResolver(self.graph)

    def test_creates_new_identity_on_first_seen(self):
        result = self.resolver.resolve(
            application_id="ucmc",
            touchpoints=[email_tp("new@user.com")],
            entity_id="buyer_001",
        )
        assert result.created is True
        assert result.identity.canonical_email == "new@user.com"
        assert result.identity.entity_ids.get("ucmc") == "buyer_001"

    def test_returns_existing_identity_on_second_resolve(self):
        self.resolver.resolve(
            application_id="ucmc",
            touchpoints=[email_tp("existing@user.com")],
        )
        result = self.resolver.resolve(
            application_id="ucmc",
            touchpoints=[email_tp("existing@user.com")],
        )
        assert result.created is False
        assert self.graph.size() == 1

    def test_merges_when_multiple_identities_match(self):
        # Create two separate identities
        self.resolver.resolve(
            application_id="ucmc",
            touchpoints=[email_tp("user@x.com")],
        )
        self.resolver.resolve(
            application_id="ucmc",
            touchpoints=[device_tp("device_abc")],
        )
        assert self.graph.size() == 2

        # Now resolve with BOTH touchpoints — should merge
        result = self.resolver.resolve(
            application_id="ucmc",
            touchpoints=[email_tp("user@x.com"), device_tp("device_abc")],
        )
        assert result.merged is True

    def test_adds_new_touchpoints_to_existing_identity(self):
        r1 = self.resolver.resolve(
            application_id="ucmc",
            touchpoints=[email_tp("user@x.com")],
        )
        r2 = self.resolver.resolve(
            application_id="ucmc",
            touchpoints=[email_tp("user@x.com"), device_tp("device_new")],
        )
        assert r2.touchpoints_added == 1
        assert r2.identity.id == r1.identity.id

    def test_resolve_from_event_stamps_identity_id(self):
        event = Event(
            application_id="ucmc",
            type=EventType.USER_REGISTERED,
            actor_id="buyer_001",
            actor_type="Buyer",
            properties={"email": "fromEVENT@test.com"},
        )
        result = self.resolver.resolve_from_event(event)
        assert result is not None
        assert event.identity_id is not None
        assert event.identity_id == result.identity.id

    def test_resolve_from_event_uses_device_context(self):
        event = Event(
            application_id="ucmc",
            type=EventType.SESSION_STARTED,
            actor_id="anon_001",
            actor_type="User",
            context=EventContext(
                device=DeviceContext(device_id="device_context_001")
            ),
        )
        result = self.resolver.resolve_from_event(event)
        assert result is not None
        device_found = any(
            tp.type == TouchpointType.DEVICE_ID
            for tp in result.identity.touchpoints
        )
        assert device_found

    def test_traits_applied_during_resolve(self):
        result = self.resolver.resolve(
            application_id="ucmc",
            touchpoints=[email_tp("t@t.com")],
            traits={"country": "NG", "plan": "free"},
        )
        assert result.identity.traits["country"] == "NG"
        assert result.identity.traits["plan"] == "free"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
