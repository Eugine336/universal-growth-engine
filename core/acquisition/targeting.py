"""
Targeting Spec Builder

Translates category-level audience archetypes into
channel-specific targeting specs.
"""

from __future__ import annotations

from typing import List, Optional

from core.cold_start.category import AudienceArchetype

from .schema import AudienceSpec


_CHANNEL_PLATFORMS = {
    "linkedin": ["linkedin"],
    "meta": ["facebook", "instagram"],
    "google_search": ["google"],
    "tiktok": ["tiktok"],
    "community": ["discord", "reddit", "whatsapp"],
    "content": ["blog", "youtube"],
    "referral": ["email", "whatsapp"],
}


class TargetingSpecBuilder:

    def build(
        self,
        archetype: AudienceArchetype,
        channel: str,
        regions: Optional[List[str]] = None,
    ) -> AudienceSpec:
        locations = regions or []

        if channel == "linkedin":
            return AudienceSpec(
                name=f"{archetype.name} — LinkedIn",
                description=f"LinkedIn targeting for {archetype.description}",
                age_min=archetype.age_range[0],
                age_max=archetype.age_range[1],
                interests=archetype.interests,
                job_titles=archetype.job_titles,
                locations=locations,
                platforms=["linkedin"],
                source="category_knowledge",
            )

        if channel == "meta":
            return AudienceSpec(
                name=f"{archetype.name} — Meta",
                description=f"Meta interest targeting for {archetype.description}",
                age_min=archetype.age_range[0],
                age_max=archetype.age_range[1],
                interests=archetype.interests + archetype.pain_points[:2],
                job_titles=[],
                locations=locations,
                platforms=["facebook", "instagram"],
                source="category_knowledge",
            )

        if channel == "google_search":
            keywords = archetype.interests + [
                p.replace(" ", " ") for p in archetype.pain_points[:3]
            ]
            return AudienceSpec(
                name=f"{archetype.name} — Google",
                description=f"Google search targeting for {archetype.description}",
                age_min=archetype.age_range[0],
                age_max=archetype.age_range[1],
                interests=keywords,
                job_titles=[],
                locations=locations,
                platforms=["google"],
                source="category_knowledge",
            )

        if channel == "tiktok":
            return AudienceSpec(
                name=f"{archetype.name} — TikTok",
                description=f"TikTok interest targeting for {archetype.description}",
                age_min=max(archetype.age_range[0], 18),
                age_max=min(archetype.age_range[1], 45),
                interests=archetype.interests,
                job_titles=[],
                locations=locations,
                platforms=["tiktok"],
                source="category_knowledge",
            )

        return AudienceSpec(
            name=f"{archetype.name} — {channel}",
            description=f"{channel} targeting for {archetype.description}",
            age_min=archetype.age_range[0],
            age_max=archetype.age_range[1],
            interests=archetype.interests,
            job_titles=archetype.job_titles,
            locations=locations,
            platforms=_CHANNEL_PLATFORMS.get(channel, [channel]),
            source="category_knowledge",
        )
