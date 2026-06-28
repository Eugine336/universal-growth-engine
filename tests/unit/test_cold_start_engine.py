"""Unit tests for ColdStartEngine."""

from __future__ import annotations

import pytest

from core.cold_start.engine import ColdStartEngine, ColdStartResult
from core.decision.policy import PolicyRegistry


@pytest.fixture()
def policy_registry():
    return PolicyRegistry()


@pytest.fixture()
def engine(policy_registry):
    return ColdStartEngine(policy_registry=policy_registry)


class TestColdStartEngine:

    def test_run_returns_result(self, engine):
        result = engine.run(
            platform_id="test-platform",
            name="Test Marketplace",
            entity_types=["Seller", "Buyer", "Listing"],
            objectives=["GMV"],
        )
        assert isinstance(result, ColdStartResult)
        assert result.platform_id == "test-platform"
        assert result.category.category_id == "b2b_marketplace"
        assert result.policies_registered > 0

    def test_policies_registered_in_registry(self, engine, policy_registry):
        initial = policy_registry.count("test-plat")
        engine.run(
            platform_id="test-plat",
            name="SaaS Tool",
            entity_types=["User", "Workspace"],
            objectives=["MRR", "activation"],
        )
        after = policy_registry.count("test-plat")
        assert after > initial

    def test_playbook_included_in_result(self, engine):
        result = engine.run(
            platform_id="p1",
            name="EdTech",
            entity_types=["Student", "Course"],
            objectives=["enrollment"],
        )
        assert result.playbook is not None
        assert result.playbook.platform_id == "p1"
        assert len(result.playbook.activation_sequence) >= 4

    def test_get_result_after_run(self, engine):
        engine.run(platform_id="p1", name="Test", category_hint="saas")
        result = engine.get_result("p1")
        assert result is not None
        assert result.platform_id == "p1"

    def test_get_result_returns_none_before_run(self, engine):
        assert engine.get_result("nonexistent") is None

    def test_get_playbook_after_run(self, engine):
        engine.run(platform_id="p1", name="Test", category_hint="edtech")
        playbook = engine.get_playbook("p1")
        assert playbook is not None
        assert playbook.category.category_id == "edtech"

    def test_with_category_hint(self, engine):
        result = engine.run(
            platform_id="p1",
            name="Something",
            category_hint="healthtech",
        )
        assert result.category.category_id == "healthtech"
        assert result.category.confidence == 1.0

    def test_generic_fallback(self, engine):
        result = engine.run(
            platform_id="p1",
            name="Unknown App",
            entity_types=["Widget"],
        )
        assert result.category.category_id == "generic"
        assert result.policies_registered > 0

    def test_with_acquisition_engine(self, policy_registry):
        from core.acquisition.engine import AcquisitionEngine
        acq = AcquisitionEngine()
        engine = ColdStartEngine(
            policy_registry=policy_registry,
            acquisition_engine=acq,
        )
        result = engine.run(
            platform_id="p1",
            name="Marketplace",
            entity_types=["Seller", "Buyer"],
            objectives=["GMV"],
        )
        assert result.acquisition_plan is not None
        assert result.acquisition_plan.platform_id == "p1"
        assert result.acquisition_plan.stage == "cold"
