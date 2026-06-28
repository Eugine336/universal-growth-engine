"""Unit tests for TargetingSpecBuilder and MessageTemplateEngine."""

from __future__ import annotations

import pytest

from core.acquisition.messaging import MessageTemplateEngine
from core.acquisition.targeting import TargetingSpecBuilder
from core.cold_start.category import AudienceArchetype


@pytest.fixture()
def archetype():
    return AudienceArchetype(
        name="SME Founder",
        description="Small business owner looking for services",
        age_range=(28, 50),
        job_titles=["CEO", "Founder", "Managing Director"],
        interests=["entrepreneurship", "business growth", "outsourcing"],
        pain_points=["finding reliable providers", "vetting quality"],
        channels=["linkedin", "google_search"],
        message_tone="professional",
        primary_motivation="Find vetted service providers",
    )


@pytest.fixture()
def targeting():
    return TargetingSpecBuilder()


@pytest.fixture()
def messaging():
    return MessageTemplateEngine()


class TestTargetingSpecBuilder:

    def test_linkedin_includes_job_titles(self, targeting, archetype):
        spec = targeting.build(archetype, "linkedin", regions=["KE"])
        assert "CEO" in spec.job_titles
        assert "Founder" in spec.job_titles
        assert "linkedin" in spec.platforms
        assert "KE" in spec.locations

    def test_meta_includes_interests_and_pain_points(self, targeting, archetype):
        spec = targeting.build(archetype, "meta")
        assert "entrepreneurship" in spec.interests
        assert any("finding" in i or "vetting" in i for i in spec.interests)
        assert "facebook" in spec.platforms

    def test_google_includes_keywords(self, targeting, archetype):
        spec = targeting.build(archetype, "google_search")
        assert "google" in spec.platforms
        assert len(spec.interests) >= 3

    def test_tiktok_age_capped(self, targeting):
        young_archetype = AudienceArchetype(
            name="Young Creator",
            description="Young content creator",
            age_range=(14, 50),
            job_titles=[],
            interests=["social media"],
            pain_points=["growth"],
            channels=["tiktok"],
            message_tone="casual",
            primary_motivation="Grow audience",
        )
        spec = targeting.build(young_archetype, "tiktok")
        assert spec.age_min >= 18
        assert spec.age_max <= 45
        assert "tiktok" in spec.platforms

    def test_unknown_channel_uses_defaults(self, targeting, archetype):
        spec = targeting.build(archetype, "whatsapp")
        assert spec.name == "SME Founder — whatsapp"
        assert spec.age_min == 28
        assert spec.age_max == 50

    def test_regions_passed_through(self, targeting, archetype):
        spec = targeting.build(archetype, "linkedin", regions=["KE", "NG", "GH"])
        assert spec.locations == ["KE", "NG", "GH"]

    def test_source_is_category_knowledge(self, targeting, archetype):
        spec = targeting.build(archetype, "meta")
        assert spec.source == "category_knowledge"


class TestMessageTemplateEngine:

    def test_awareness_headline_uses_pain_point(self, messaging, archetype):
        creative = messaging.generate(archetype, "linkedin", stage="awareness")
        assert "finding reliable providers" in creative.headline.lower()
        assert creative.tone == "professional"

    def test_consideration_headline(self, messaging, archetype):
        creative = messaging.generate(archetype, "meta", stage="consideration")
        assert "choose" in creative.headline.lower() or "sme" in creative.headline.lower()

    def test_conversion_uses_value_prop(self, messaging, archetype):
        creative = messaging.generate(archetype, "google_search", stage="conversion", value_prop="Best marketplace")
        assert "Best marketplace" in creative.headline or "Best marketplace" in creative.body

    def test_retention_stage(self, messaging, archetype):
        creative = messaging.generate(archetype, "meta", stage="retention")
        assert creative.cta

    def test_professional_tone_cta(self, messaging, archetype):
        creative = messaging.generate(archetype, "linkedin", stage="awareness")
        assert creative.cta == "Learn More"

    def test_casual_tone_cta(self, messaging):
        casual = AudienceArchetype(
            name="Shopper", description="Consumer", age_range=(18, 35),
            job_titles=[], interests=["shopping"], pain_points=["prices"],
            channels=["meta"], message_tone="casual",
            primary_motivation="Find deals",
        )
        creative = messaging.generate(casual, "meta", stage="awareness")
        assert creative.cta == "Check It Out"

    def test_channel_format_mapping(self, messaging, archetype):
        linkedin = messaging.generate(archetype, "linkedin")
        assert linkedin.format == "single_image"
        google = messaging.generate(archetype, "google_search")
        assert google.format == "search_text"
        tiktok = messaging.generate(archetype, "tiktok")
        assert tiktok.format == "video"
        meta = messaging.generate(archetype, "meta")
        assert meta.format == "carousel"
