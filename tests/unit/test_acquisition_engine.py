"""Unit tests for AcquisitionEngine."""

from __future__ import annotations

import pytest

from core.acquisition.engine import AcquisitionEngine
from core.acquisition.schema import AcquisitionPlan
from core.behavior.repository import BehaviorRepository
from core.behavior.schema import BehavioralProfile
from core.cold_start.category import CategoryClassifier, CategoryKnowledgeBase
from core.cold_start.playbook import PlaybookGenerator


def _make_playbook(category_hint="b2b_marketplace"):
    classifier = CategoryClassifier()
    kb = CategoryKnowledgeBase()
    pg = PlaybookGenerator()
    cat = classifier.classify(category_hint=category_hint)
    knowledge = kb.get(cat.category_id)
    return pg.generate("test-plat", cat, knowledge)


@pytest.fixture()
def behavior_repo():
    return BehaviorRepository()


@pytest.fixture()
def engine():
    return AcquisitionEngine()


@pytest.fixture()
def engine_with_repo(behavior_repo):
    return AcquisitionEngine(behavior_repo=behavior_repo)


class TestAcquisitionEngineColdMode:

    def test_build_plan_returns_plan(self, engine):
        playbook = _make_playbook("saas")
        plan = engine.build_plan("test-plat", playbook)
        assert isinstance(plan, AcquisitionPlan)
        assert plan.platform_id == "test-plat"
        assert plan.stage == "cold"

    def test_cold_plan_has_no_lookalikes(self, engine):
        playbook = _make_playbook("edtech")
        plan = engine.build_plan("p1", playbook)
        assert len(plan.lookalike_seeds) == 0

    def test_cold_plan_has_channel_plans(self, engine):
        playbook = _make_playbook("b2b_marketplace")
        plan = engine.build_plan("p1", playbook)
        assert len(plan.channel_plans) >= 3
        channels = [cp.channel for cp in plan.channel_plans]
        assert "linkedin" in channels

    def test_cold_plan_has_creatives(self, engine):
        playbook = _make_playbook("ecommerce")
        plan = engine.build_plan("p1", playbook)
        assert len(plan.creative_specs) >= 3
        for cs in plan.creative_specs:
            assert cs.headline
            assert cs.cta

    def test_cold_plan_has_seed_audiences(self, engine):
        playbook = _make_playbook("healthtech")
        plan = engine.build_plan("p1", playbook)
        assert len(plan.seed_audiences) >= 3
        for sa in plan.seed_audiences:
            assert sa.source == "category_knowledge"

    def test_get_plan_after_build(self, engine):
        playbook = _make_playbook("saas")
        engine.build_plan("p1", playbook)
        plan = engine.get_plan("p1")
        assert plan is not None

    def test_get_plan_returns_none_before_build(self, engine):
        assert engine.get_plan("nonexistent") is None

    def test_estimated_cac_set(self, engine):
        playbook = _make_playbook("fintech_trading")
        plan = engine.build_plan("p1", playbook)
        assert plan.estimated_cac is not None
        assert plan.estimated_cac > 0

    def test_channel_plan_cac_ranges(self, engine):
        playbook = _make_playbook("b2b_marketplace")
        plan = engine.build_plan("p1", playbook)
        for cp in plan.channel_plans:
            low, high = cp.expected_cac_range
            assert high > low > 0


class TestAcquisitionEngineWarmMode:

    def test_warm_mode_activates_with_enough_profiles(self, engine_with_repo, behavior_repo):
        playbook = _make_playbook("saas")
        for i in range(20):
            p = BehavioralProfile(identity_id=f"u{i}", application_id="test-plat")
            p.rfm.total_monetary_value = float(i * 100)
            behavior_repo.save(p)

        plan = engine_with_repo.refresh_plan("test-plat", playbook)
        assert plan.stage == "warm"
        assert len(plan.lookalike_seeds) >= 2

    def test_warm_mode_has_lookalike_seeds(self, engine_with_repo, behavior_repo):
        playbook = _make_playbook("ecommerce")
        for i in range(15):
            p = BehavioralProfile(identity_id=f"u{i}", application_id="test-plat")
            p.rfm.total_monetary_value = float(i * 50)
            behavior_repo.save(p)

        plan = engine_with_repo.refresh_plan("test-plat", playbook)
        platforms = [ls.platform for ls in plan.lookalike_seeds]
        assert "meta" in platforms
        assert "google" in platforms

    def test_stays_cold_with_few_profiles(self, engine_with_repo, behavior_repo):
        playbook = _make_playbook("saas")
        for i in range(5):
            behavior_repo.save(BehavioralProfile(identity_id=f"u{i}", application_id="test-plat"))

        plan = engine_with_repo.refresh_plan("test-plat", playbook)
        assert plan.stage == "cold"
        assert len(plan.lookalike_seeds) == 0
