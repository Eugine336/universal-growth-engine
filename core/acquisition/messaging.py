"""
Message Template Engine

Generates ad creative specs from archetypes, channels, and stages.
"""

from __future__ import annotations

from typing import Optional

from core.cold_start.category import AudienceArchetype

from .schema import AdCreativeSpec


_STAGE_FOCUS = {
    "awareness": "pain_point",
    "consideration": "differentiation",
    "conversion": "offer",
    "retention": "value_reinforcement",
}

_TONE_CTA = {
    "professional": {"awareness": "Learn More", "consideration": "See How It Works", "conversion": "Start Free Trial", "retention": "Upgrade Now"},
    "casual": {"awareness": "Check It Out", "consideration": "See What's New", "conversion": "Get Started Free", "retention": "Keep Going"},
}

_CHANNEL_FORMAT = {
    "linkedin": "single_image",
    "meta": "carousel",
    "google_search": "search_text",
    "tiktok": "video",
    "content": "single_image",
    "community": "single_image",
    "referral": "single_image",
}


class MessageTemplateEngine:

    def generate(
        self,
        archetype: AudienceArchetype,
        channel: str,
        stage: str = "awareness",
        value_prop: str = "",
    ) -> AdCreativeSpec:
        tone = archetype.message_tone
        cta_map = _TONE_CTA.get(tone, _TONE_CTA["casual"])
        cta = cta_map.get(stage, "Learn More")
        fmt = _CHANNEL_FORMAT.get(channel, "single_image")

        headline = self._build_headline(archetype, stage, value_prop)
        body = self._build_body(archetype, stage, value_prop)

        return AdCreativeSpec(
            channel=channel,
            format=fmt,
            headline=headline,
            body=body,
            cta=cta,
            tone=tone,
            value_prop=value_prop,
        )

    def _build_headline(
        self,
        archetype: AudienceArchetype,
        stage: str,
        value_prop: str,
    ) -> str:
        if stage == "awareness":
            pain = archetype.pain_points[0] if archetype.pain_points else "your biggest challenge"
            return f"Struggling with {pain}?"
        if stage == "consideration":
            return f"Why {archetype.name}s choose us"
        if stage == "conversion":
            return value_prop or archetype.primary_motivation
        return f"Unlock more with {value_prop}" if value_prop else "Keep achieving"

    def _build_body(
        self,
        archetype: AudienceArchetype,
        stage: str,
        value_prop: str,
    ) -> str:
        if stage == "awareness":
            motivation = archetype.primary_motivation
            return f"{motivation}. Join thousands who already did."
        if stage == "consideration":
            interests = ", ".join(archetype.interests[:3]) if archetype.interests else "your goals"
            return f"Built for {interests}. See the difference."
        if stage == "conversion":
            return f"Start today — {value_prop}. No commitment required."
        return f"You're already seeing results. Take the next step."
