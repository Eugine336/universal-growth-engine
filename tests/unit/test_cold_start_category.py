"""Unit tests for CategoryClassifier and CategoryKnowledgeBase."""

from __future__ import annotations

import pytest

from core.cold_start.category import (
    CategoryClassifier,
    CategoryKnowledgeBase,
    CategoryProfile,
)


@pytest.fixture()
def classifier():
    return CategoryClassifier()


@pytest.fixture()
def knowledge_base():
    return CategoryKnowledgeBase()


class TestCategoryClassifier:

    def test_classifies_b2b_marketplace(self, classifier):
        result = classifier.classify(
            name="UCMC Marketplace",
            entity_types=["Seller", "Buyer", "Listing", "Escrow"],
            objectives=["GMV", "marketplace liquidity"],
        )
        assert result.category_id == "b2b_marketplace"
        assert result.confidence > 0.3
        assert not result.fallback

    def test_classifies_saas(self, classifier):
        result = classifier.classify(
            name="Workflow Tool",
            entity_types=["User", "Workspace", "Subscription"],
            objectives=["MRR", "retention", "activation"],
        )
        assert result.category_id == "saas"
        assert not result.fallback

    def test_classifies_fintech_trading(self, classifier):
        result = classifier.classify(
            name="Trading Platform",
            entity_types=["Trader", "Portfolio", "Trade"],
            objectives=["trading volume", "AUM"],
        )
        assert result.category_id == "fintech_trading"
        assert not result.fallback

    def test_classifies_fintech_payments(self, classifier):
        result = classifier.classify(
            name="Payment Gateway",
            entity_types=["Wallet", "Payment", "Merchant"],
            objectives=["TPV", "payments"],
        )
        assert result.category_id == "fintech_payments"
        assert not result.fallback

    def test_classifies_edtech(self, classifier):
        result = classifier.classify(
            name="Online Learning",
            entity_types=["Student", "Course", "Instructor", "Enrollment"],
            objectives=["enrollment", "completion"],
        )
        assert result.category_id == "edtech"
        assert not result.fallback

    def test_classifies_healthtech(self, classifier):
        result = classifier.classify(
            name="FitNaija",
            entity_types=["Member", "Workout", "Appointment"],
            objectives=["wellness", "fitness"],
        )
        assert result.category_id == "healthtech"
        assert not result.fallback

    def test_classifies_ecommerce(self, classifier):
        result = classifier.classify(
            name="Online Shop",
            entity_types=["Product", "Cart", "Order", "Customer"],
            objectives=["revenue", "AOV", "conversion"],
        )
        assert result.category_id == "ecommerce"
        assert not result.fallback

    def test_classifies_social(self, classifier):
        result = classifier.classify(
            name="Community App",
            entity_types=["User", "Post", "Comment", "Follow"],
            objectives=["DAU", "engagement", "community"],
        )
        assert result.category_id == "social"
        assert not result.fallback

    def test_classifies_developer_tools(self, classifier):
        result = classifier.classify(
            name="API Platform",
            entity_types=["Developer", "API", "Key", "Endpoint"],
            objectives=["developer adoption", "API calls"],
        )
        assert result.category_id == "developer_tools"
        assert not result.fallback

    def test_classifies_b2c_marketplace(self, classifier):
        result = classifier.classify(
            name="Consumer Marketplace",
            entity_types=["Buyer", "Product", "Review", "Wishlist"],
            objectives=["consumer", "shopping"],
        )
        assert result.category_id in ("b2c_marketplace", "b2b_marketplace", "ecommerce")
        assert not result.fallback

    def test_falls_back_to_generic(self, classifier):
        result = classifier.classify(
            name="MyApp",
            entity_types=["Thing", "Widget"],
            objectives=["growth"],
        )
        assert result.category_id == "generic"
        assert result.fallback
        assert result.confidence == 0.0

    def test_category_hint_overrides(self, classifier):
        result = classifier.classify(
            name="Random Name",
            category_hint="edtech",
        )
        assert result.category_id == "edtech"
        assert result.confidence == 1.0
        assert not result.fallback

    def test_confidence_reflects_match_quality(self, classifier):
        strong = classifier.classify(
            entity_types=["Trader", "Account", "Position", "Portfolio", "Trade", "Order"],
            objectives=["trading", "investment", "portfolio"],
        )
        weak = classifier.classify(
            entity_types=["Trade"],
        )
        assert strong.confidence > weak.confidence

    def test_matched_signals_populated(self, classifier):
        result = classifier.classify(
            entity_types=["Student", "Course"],
            objectives=["learning"],
        )
        assert len(result.matched_signals) > 0
        assert any("entity:" in s for s in result.matched_signals)


class TestCategoryKnowledgeBase:

    def test_has_all_11_categories(self, knowledge_base):
        cats = knowledge_base.list_categories()
        assert len(cats) == 11
        assert "b2b_marketplace" in cats
        assert "generic" in cats

    def test_get_returns_knowledge(self, knowledge_base):
        k = knowledge_base.get("b2b_marketplace")
        assert k is not None
        assert k.category_id == "b2b_marketplace"
        assert len(k.audience_archetypes) > 0
        assert len(k.acquisition_channels) > 0
        assert len(k.activation_events) > 0
        assert k.cold_start_window_days > 0

    def test_budget_split_sums_to_one(self, knowledge_base):
        for cat_id in knowledge_base.list_categories():
            k = knowledge_base.get(cat_id)
            total = sum(k.default_budget_split.values())
            assert abs(total - 1.0) < 0.01, f"{cat_id} budget split sums to {total}"

    def test_unknown_category_falls_back_to_generic(self, knowledge_base):
        k = knowledge_base.get("nonexistent")
        assert k is not None
        assert k.category_id == "generic"

    def test_each_category_has_archetypes(self, knowledge_base):
        for cat_id in knowledge_base.list_categories():
            k = knowledge_base.get(cat_id)
            assert len(k.audience_archetypes) >= 1, f"{cat_id} has no archetypes"
            a = k.audience_archetypes[0]
            assert a.name
            assert a.age_range[0] < a.age_range[1]

    def test_each_category_has_kpis(self, knowledge_base):
        for cat_id in knowledge_base.list_categories():
            k = knowledge_base.get(cat_id)
            assert len(k.primary_kpis) >= 2, f"{cat_id} needs KPIs"

    def test_cac_ranges_valid(self, knowledge_base):
        for cat_id in knowledge_base.list_categories():
            k = knowledge_base.get(cat_id)
            low, high = k.typical_cac_range
            assert low > 0
            assert high > low, f"{cat_id} CAC range invalid"
