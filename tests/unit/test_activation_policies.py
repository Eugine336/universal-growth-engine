"""Unit tests for ActivationPolicyGenerator."""

from __future__ import annotations

import pytest

from core.cold_start.activation import ActivationPolicyGenerator
from core.cold_start.category import CategoryClassifier, CategoryKnowledgeBase
from core.cold_start.playbook import PlaybookGenerator
from core.decision.policy import PolicyRegistry
from core.decision.schema import ActionType


@pytest.fixture()
def policy_registry():
    return PolicyRegistry()


@pytest.fixture()
def generator():
    return ActivationPolicyGenerator()


def _make_playbook(category_hint="b2b_marketplace"):
    classifier = CategoryClassifier()
    kb = CategoryKnowledgeBase()
    pg = PlaybookGenerator()
    cat = classifier.classify(category_hint=category_hint)
    knowledge = kb.get(cat.category_id)
    return pg.generate("test-plat", cat, knowledge)


class TestActivationPolicyGenerator:

    def test_generates_policies(self, generator, policy_registry):
        playbook = _make_playbook("b2b_marketplace")
        policies = generator.generate_policies(playbook, policy_registry)
        assert len(policies) >= 5

    def test_policies_registered_in_registry(self, generator, policy_registry):
        playbook = _make_playbook("saas")
        policies = generator.generate_policies(playbook, policy_registry)
        for p in policies:
            found = policy_registry.get(p.id)
            assert found is not None

    def test_welcome_policy_present(self, generator, policy_registry):
        playbook = _make_playbook("edtech")
        policies = generator.generate_policies(playbook, policy_registry)
        names = [p.name for p in policies]
        assert "Welcome & Profile Completion" in names

    def test_welcome_policy_triggers_on_user_registered(self, generator, policy_registry):
        playbook = _make_playbook("ecommerce")
        policies = generator.generate_policies(playbook, policy_registry)
        welcome = next(p for p in policies if "Welcome" in p.name)
        assert "USER_REGISTERED" in welcome.trigger_events
        assert welcome.action.action_type == ActionType.SHOW_ONBOARDING

    def test_policies_have_correct_application_id(self, generator, policy_registry):
        playbook = _make_playbook("healthtech")
        policies = generator.generate_policies(playbook, policy_registry)
        for p in policies:
            assert p.application_id == "test-plat"

    def test_priority_ladder(self, generator, policy_registry):
        playbook = _make_playbook("b2b_marketplace")
        policies = generator.generate_policies(playbook, policy_registry)
        welcome = next(p for p in policies if "Welcome" in p.name)
        reeng_48h = next(p for p in policies if "48h" in p.name)
        reeng_7d = next(p for p in policies if "7 Day" in p.name)
        assert welcome.action.priority > reeng_48h.action.priority
        assert reeng_48h.action.priority > reeng_7d.action.priority

    def test_abort_if_events_on_reengagement(self, generator, policy_registry):
        playbook = _make_playbook("saas")
        policies = generator.generate_policies(playbook, policy_registry)
        reeng = next(p for p in policies if "48h" in p.name)
        assert "SESSION_STARTED" in reeng.abort_if_events

    def test_marketplace_has_celebration_policy(self, generator, policy_registry):
        playbook = _make_playbook("b2b_marketplace")
        policies = generator.generate_policies(playbook, policy_registry)
        names = [p.name for p in policies]
        assert "First Transaction Celebration" in names

    def test_marketplace_has_referral_ask(self, generator, policy_registry):
        playbook = _make_playbook("b2b_marketplace")
        policies = generator.generate_policies(playbook, policy_registry)
        names = [p.name for p in policies]
        assert "Post-First-Win Referral Ask" in names

    def test_referral_ask_has_delay(self, generator, policy_registry):
        playbook = _make_playbook("ecommerce")
        policies = generator.generate_policies(playbook, policy_registry)
        referral = next((p for p in policies if "Referral" in p.name), None)
        if referral:
            assert referral.action.delay_hours >= 24.0

    def test_max_executions_set(self, generator, policy_registry):
        playbook = _make_playbook("saas")
        policies = generator.generate_policies(playbook, policy_registry)
        welcome = next(p for p in policies if "Welcome" in p.name)
        assert welcome.max_executions_per_identity == 1

    def test_upsell_policy_present(self, generator, policy_registry):
        playbook = _make_playbook("saas")
        policies = generator.generate_policies(playbook, policy_registry)
        names = [p.name for p in policies]
        assert "Active User Upsell" in names
