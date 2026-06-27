"""Unit tests for Platform schema and registry."""

import pytest

from core.platform.schema import (
    Platform,
    PlatformQuotas,
    PlatformStatus,
    generate_api_key,
    hash_api_key,
)
from core.platform.registry import PlatformRegistry


# ======================================================================
# Schema Tests
# ======================================================================

class TestPlatformSchema:

    def test_default_platform_creation(self):
        p = Platform(name="Test", slug="test", owner_email="a@b.com")
        assert p.name == "Test"
        assert p.slug == "test"
        assert p.status == PlatformStatus.ACTIVE
        assert p.id
        assert p.quotas.max_events_per_hour == 10000

    def test_set_and_verify_api_key(self):
        p = Platform(name="T", slug="t", owner_email="a@b.com")
        raw = generate_api_key()
        p.set_api_key(raw)
        assert p.api_key_hash
        assert p.api_key_prefix == raw[:8]
        assert p.verify_api_key(raw)
        assert not p.verify_api_key("wrong_key")

    def test_generate_api_key_format(self):
        key = generate_api_key()
        assert key.startswith("ugie_")
        assert len(key) == 37  # "ugie_" + 32 hex chars

    def test_hash_api_key_deterministic(self):
        h1 = hash_api_key("test_key")
        h2 = hash_api_key("test_key")
        assert h1 == h2
        assert hash_api_key("other") != h1

    def test_is_active(self):
        p = Platform(name="T", slug="t", owner_email="a@b.com")
        assert p.is_active()
        p.status = PlatformStatus.SUSPENDED
        assert not p.is_active()
        p.status = PlatformStatus.DEACTIVATED
        assert not p.is_active()

    def test_quotas_defaults(self):
        q = PlatformQuotas()
        assert q.max_events_per_hour == 10000
        assert q.max_entities == 100000
        assert q.max_decisions_per_hour == 5000

    def test_quotas_custom(self):
        q = PlatformQuotas(max_events_per_hour=500, max_entities=1000)
        assert q.max_events_per_hour == 500
        assert q.max_entities == 1000
        assert q.max_decisions_per_hour == 5000


# ======================================================================
# Registry Tests
# ======================================================================

class TestPlatformRegistry:

    def setup_method(self):
        self.registry = PlatformRegistry()

    def test_register_platform(self):
        platform, raw_key = self.registry.register(
            name="UCMC", slug="ucmc", owner_email="admin@ucmc.io"
        )
        assert platform.name == "UCMC"
        assert platform.slug == "ucmc"
        assert platform.status == PlatformStatus.ACTIVE
        assert raw_key.startswith("ugie_")
        assert platform.api_key_prefix == raw_key[:8]

    def test_register_duplicate_slug_raises(self):
        self.registry.register(name="A", slug="myslug", owner_email="a@b.com")
        with pytest.raises(ValueError, match="already taken"):
            self.registry.register(name="B", slug="myslug", owner_email="c@d.com")

    def test_register_invalid_slug_raises(self):
        with pytest.raises(ValueError, match="Invalid slug"):
            self.registry.register(name="A", slug="AB", owner_email="a@b.com")
        with pytest.raises(ValueError, match="Invalid slug"):
            self.registry.register(name="A", slug="a", owner_email="a@b.com")

    def test_get_by_id(self):
        platform, _ = self.registry.register(name="P", slug="ppp", owner_email="a@b.com")
        found = self.registry.get_by_id(platform.id)
        assert found is not None
        assert found.name == "P"

    def test_get_by_id_not_found(self):
        assert self.registry.get_by_id("nonexistent") is None

    def test_get_by_slug(self):
        self.registry.register(name="P", slug="myapp", owner_email="a@b.com")
        found = self.registry.get_by_slug("myapp")
        assert found is not None
        assert found.slug == "myapp"

    def test_get_by_slug_not_found(self):
        assert self.registry.get_by_slug("nope") is None

    def test_get_by_api_key(self):
        platform, raw_key = self.registry.register(
            name="P", slug="lookup", owner_email="a@b.com"
        )
        found = self.registry.get_by_api_key(raw_key)
        assert found is not None
        assert found.id == platform.id

    def test_get_by_api_key_invalid(self):
        assert self.registry.get_by_api_key("ugie_fakefakefake") is None

    def test_list_platforms(self):
        self.registry.register(name="A", slug="aaa", owner_email="a@b.com")
        self.registry.register(name="B", slug="bbb", owner_email="c@d.com")
        all_p = self.registry.list_platforms()
        assert len(all_p) == 2

    def test_list_platforms_by_status(self):
        p1, _ = self.registry.register(name="A", slug="act", owner_email="a@b.com")
        p2, _ = self.registry.register(name="B", slug="sus", owner_email="c@d.com")
        self.registry.suspend(p2.id)
        active = self.registry.list_platforms(status=PlatformStatus.ACTIVE)
        assert len(active) == 1
        assert active[0].id == p1.id

    def test_update_platform(self):
        platform, _ = self.registry.register(name="Old", slug="upd", owner_email="a@b.com")
        updated = self.registry.update(platform.id, name="New", owner_email="new@b.com")
        assert updated.name == "New"
        assert updated.owner_email == "new@b.com"

    def test_update_nonexistent_returns_none(self):
        assert self.registry.update("fake", name="X") is None

    def test_update_quotas(self):
        platform, _ = self.registry.register(name="Q", slug="quo", owner_email="a@b.com")
        new_q = PlatformQuotas(max_events_per_hour=999)
        self.registry.update(platform.id, quotas=new_q)
        found = self.registry.get_by_id(platform.id)
        assert found.quotas.max_events_per_hour == 999

    def test_deactivate(self):
        platform, raw_key = self.registry.register(
            name="D", slug="deact", owner_email="a@b.com"
        )
        self.registry.deactivate(platform.id)
        found = self.registry.get_by_id(platform.id)
        assert found.status == PlatformStatus.DEACTIVATED
        assert self.registry.get_by_api_key(raw_key) is None

    def test_deactivate_nonexistent(self):
        assert self.registry.deactivate("fake") is None

    def test_suspend(self):
        platform, _ = self.registry.register(name="S", slug="susp", owner_email="a@b.com")
        self.registry.suspend(platform.id)
        found = self.registry.get_by_id(platform.id)
        assert found.status == PlatformStatus.SUSPENDED

    def test_rotate_api_key(self):
        platform, old_key = self.registry.register(
            name="R", slug="rot", owner_email="a@b.com"
        )
        result = self.registry.rotate_api_key(platform.id)
        assert result is not None
        updated, new_key = result
        assert new_key != old_key
        assert self.registry.get_by_api_key(old_key) is None
        assert self.registry.get_by_api_key(new_key) is not None

    def test_rotate_nonexistent(self):
        assert self.registry.rotate_api_key("fake") is None

    def test_stats(self):
        self.registry.register(name="A", slug="sta", owner_email="a@b.com")
        p2, _ = self.registry.register(name="B", slug="stb", owner_email="c@d.com")
        self.registry.suspend(p2.id)
        s = self.registry.stats()
        assert s["total_platforms"] == 2
        assert s["by_status"]["active"] == 1
        assert s["by_status"]["suspended"] == 1

    def test_register_with_custom_quotas(self):
        q = PlatformQuotas(max_events_per_hour=50)
        platform, _ = self.registry.register(
            name="CQ", slug="cqq", owner_email="a@b.com", quotas=q
        )
        assert platform.quotas.max_events_per_hour == 50

    def test_update_config_yaml(self):
        platform, _ = self.registry.register(name="C", slug="cfg", owner_email="a@b.com")
        self.registry.update(platform.id, config_yaml="application:\n  id: test")
        found = self.registry.get_by_id(platform.id)
        assert found.config_yaml == "application:\n  id: test"

    def test_update_metadata(self):
        platform, _ = self.registry.register(name="M", slug="met", owner_email="a@b.com")
        self.registry.update(platform.id, metadata={"region": "KE"})
        found = self.registry.get_by_id(platform.id)
        assert found.metadata["region"] == "KE"
