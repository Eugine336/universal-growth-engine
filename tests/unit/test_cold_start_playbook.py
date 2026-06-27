"""Unit tests for PlaybookGenerator."""

from __future__ import annotations

import pytest

from core.cold_start.category import CategoryClassifier, CategoryKnowledgeBase
from core.cold_start.playbook import GrowthPlaybook, PlaybookGenerator


@pytest.fixture()
def classifier():
    return CategoryClassifier()


@pytest.fixture()
def kb():
    return CategoryKnowledgeBase()


@pytest.fixture()
def generator():
    return PlaybookGenerator()


class TestPlaybookGenerator:

    def test_generates_playbook_for_b2b_marketplace(self, classifier, kb, generator):
        cat = classifier.classify(entity_types=["Seller", "Buyer", "Listing"], objectives=["GMV"])
        knowledge = kb.get(cat.category_id)
        playbook = generator.generate("test-plat", cat, knowledge, platform_name="TestMarket")
        assert playbook.platform_id == "test-plat"
        assert playbook.stage == "pre_launch"
        assert playbook.primary_archetype is not None
        assert len(playbook.target_archetypes) >= 1
        assert len(playbook.acquisition_channels) >= 2

    def test_budget_split_sums_to_one(self, classifier, kb, generator):
        for cat_id in kb.list_categories():
            knowledge = kb.get(cat_id)
            cat = classifier.classify(category_hint=cat_id)
            playbook = generator.generate("p", cat, knowledge)
            total = sum(playbook.budget_split.values())
            assert abs(total - 1.0) < 0.01, f"Budget split for {cat_id} sums to {total}"

    def test_activation_sequence_has_entries(self, classifier, kb, generator):
        cat = classifier.classify(category_hint="saas")
        knowledge = kb.get("saas")
        playbook = generator.generate("p", cat, knowledge)
        assert len(playbook.activation_sequence) >= 4

    def test_activation_sequence_has_welcome(self, classifier, kb, generator):
        cat = classifier.classify(category_hint="ecommerce")
        knowledge = kb.get("ecommerce")
        playbook = generator.generate("p", cat, knowledge)
        triggers = [s.trigger for s in playbook.activation_sequence]
        assert "USER_REGISTERED" in triggers

    def test_marketplace_playbook_has_payment_steps(self, classifier, kb, generator):
        cat = classifier.classify(category_hint="b2b_marketplace")
        knowledge = kb.get("b2b_marketplace")
        playbook = generator.generate("p", cat, knowledge)
        templates = [s.message_template for s in playbook.activation_sequence]
        assert "first_win" in templates
        assert "refer_a_friend" in templates

    def test_messages_generated(self, classifier, kb, generator):
        cat = classifier.classify(category_hint="edtech")
        knowledge = kb.get("edtech")
        playbook = generator.generate("p", cat, knowledge, platform_name="LearnApp")
        assert len(playbook.primary_messages) >= 4
        ids = [m.id for m in playbook.primary_messages]
        assert "welcome" in ids
        assert "come_back" in ids

    def test_policies_generated(self, classifier, kb, generator):
        cat = classifier.classify(category_hint="b2b_marketplace")
        knowledge = kb.get("b2b_marketplace")
        playbook = generator.generate("p", cat, knowledge)
        assert len(playbook.recommended_policies) >= 5
        names = [p.name for p in playbook.recommended_policies]
        assert "Welcome & Profile Completion" in names

    def test_value_proposition_set(self, classifier, kb, generator):
        cat = classifier.classify(category_hint="fintech_trading")
        knowledge = kb.get("fintech_trading")
        playbook = generator.generate("p", cat, knowledge)
        assert playbook.value_proposition
        assert len(playbook.value_proposition) > 10

    def test_success_metrics_set(self, classifier, kb, generator):
        cat = classifier.classify(category_hint="saas")
        knowledge = kb.get("saas")
        playbook = generator.generate("p", cat, knowledge)
        assert len(playbook.success_metrics) >= 2

    def test_playbook_for_each_category(self, classifier, kb, generator):
        for cat_id in kb.list_categories():
            cat = classifier.classify(category_hint=cat_id)
            knowledge = kb.get(cat_id)
            playbook = generator.generate(f"p-{cat_id}", cat, knowledge)
            assert playbook.platform_id == f"p-{cat_id}"
            assert playbook.estimated_cac > 0
            assert playbook.cold_start_window_days > 0
