"""Unit tests for the Admin Manager."""

from __future__ import annotations

import pytest

from core.admin.manager import AdminManager
from core.admin.schema import PlatformConfigUpdate, SystemHealth
from core.behavior.repository import BehaviorRepository
from core.behavior.schema import BehavioralProfile
from core.audience.engine import AudienceEngine
from core.experimentation.engine import ExperimentationEngine
from core.events.bus import EventBus
from core.events.validator import EventValidator
from core.identity.cross_platform import CrossPlatformManager
from core.identity.graph import IdentityGraph
from core.platform.registry import PlatformRegistry
from core.prediction.engine import PredictionEngine
from core.referral.engine import ReferralEngine


class _MockPipeline:

    def __init__(self):
        self.behavior_repo = BehaviorRepository()
        self.identity_graph = IdentityGraph()
        self.prediction_engine = PredictionEngine(self.behavior_repo)
        self.experimentation_engine = ExperimentationEngine()
        self.referral_engine = ReferralEngine()
        self.audience_engine = AudienceEngine(self.behavior_repo)
        self.cross_platform_manager = CrossPlatformManager(
            self.identity_graph, self.behavior_repo
        )
        self.platform_registry = PlatformRegistry()
        self.event_bus = EventBus(validator=EventValidator())


@pytest.fixture()
def manager():
    pipe = _MockPipeline()
    return AdminManager(pipe), pipe


class TestSystemHealth:

    def test_returns_all_components(self, manager):
        mgr, _ = manager
        health = mgr.get_system_health()
        assert isinstance(health, SystemHealth)
        assert "identity_graph" in health.components
        assert "behavior_repo" in health.components
        assert "prediction_engine" in health.components
        assert "event_bus" in health.components
        assert health.total_platforms == 0

    def test_counts_platforms(self, manager):
        mgr, pipe = manager
        pipe.platform_registry.register(
            name="Test", slug="test-plat", owner_email="t@t.com"
        )
        health = mgr.get_system_health()
        assert health.total_platforms == 1


class TestListPlatformsSummary:

    def test_empty(self, manager):
        mgr, _ = manager
        assert mgr.list_platforms_summary() == []

    def test_with_platforms(self, manager):
        mgr, pipe = manager
        pipe.platform_registry.register(
            name="Alpha", slug="alpha", owner_email="a@a.com"
        )
        pipe.platform_registry.register(
            name="Beta", slug="beta", owner_email="b@b.com"
        )
        result = mgr.list_platforms_summary()
        assert len(result) == 2
        names = {p["name"] for p in result}
        assert names == {"Alpha", "Beta"}


class TestPlatformDetail:

    def test_not_found(self, manager):
        mgr, _ = manager
        assert mgr.get_platform_detail("nonexistent") is None

    def test_returns_detail(self, manager):
        mgr, pipe = manager
        plat, _, _ = pipe.platform_registry.register(
            name="Detail", slug="detail", owner_email="d@d.com"
        )
        result = mgr.get_platform_detail(plat.id)
        assert result is not None
        assert result["name"] == "Detail"
        assert result["slug"] == "detail"
        assert "quotas" in result
        assert "profile_count" in result

    def test_includes_profile_count(self, manager):
        mgr, pipe = manager
        plat, _, _ = pipe.platform_registry.register(
            name="Counted", slug="counted", owner_email="c@c.com"
        )
        p1 = BehavioralProfile(identity_id="u1", application_id=plat.id)
        pipe.behavior_repo.save(p1)
        result = mgr.get_platform_detail(plat.id)
        assert result["profile_count"] == 1


class TestUpdatePlatformConfig:

    def test_not_found(self, manager):
        mgr, _ = manager
        updates = PlatformConfigUpdate(name="New Name")
        assert mgr.update_platform_config("fake", updates) is None

    def test_update_name(self, manager):
        mgr, pipe = manager
        plat, _, _ = pipe.platform_registry.register(
            name="Old Name", slug="rename", owner_email="r@r.com"
        )
        updates = PlatformConfigUpdate(name="New Name")
        result = mgr.update_platform_config(plat.id, updates)
        assert result is not None
        assert result["name"] == "New Name"

    def test_update_metadata(self, manager):
        mgr, pipe = manager
        plat, _, _ = pipe.platform_registry.register(
            name="Meta", slug="meta-test", owner_email="m@m.com"
        )
        updates = PlatformConfigUpdate(metadata={"region": "KE"})
        result = mgr.update_platform_config(plat.id, updates)
        assert result["metadata"]["region"] == "KE"


class TestEventBusStats:

    def test_returns_stats(self, manager):
        mgr, _ = manager
        result = mgr.get_event_bus_stats()
        assert isinstance(result, dict)
