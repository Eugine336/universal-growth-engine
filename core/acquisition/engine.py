"""
Acquisition Engine

Generates acquisition plans in two modes:
- Cold mode: from category knowledge alone (no users yet)
- Warm mode: augmented with real behavioral data
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from core.cold_start.category import CategoryKnowledge
from core.cold_start.playbook import GrowthPlaybook

from .messaging import MessageTemplateEngine
from .schema import (
    AcquisitionPlan,
    AdCreativeSpec,
    AudienceSpec,
    ChannelPlan,
    LookalikeSpec,
)
from .targeting import TargetingSpecBuilder

logger = logging.getLogger(__name__)


class AcquisitionEngine:

    def __init__(
        self,
        behavior_repo: Optional[Any] = None,
        budget_allocator: Optional[Any] = None,
    ):
        self._targeting = TargetingSpecBuilder()
        self._messaging = MessageTemplateEngine()
        self._behavior_repo = behavior_repo
        self._budget_allocator = budget_allocator
        self._plans: Dict[str, AcquisitionPlan] = {}
        logger.info("AcquisitionEngine initialized")

    def build_plan(
        self,
        platform_id: str,
        playbook: GrowthPlaybook,
        regions: Optional[List[str]] = None,
    ) -> AcquisitionPlan:
        archetype = playbook.primary_archetype
        channel_plans: List[ChannelPlan] = []
        seed_audiences: List[AudienceSpec] = []
        creative_specs: List[AdCreativeSpec] = []

        for ch_rec in playbook.acquisition_channels:
            targeting = self._targeting.build(archetype, ch_rec.channel, regions)
            creative = self._messaging.generate(
                archetype,
                ch_rec.channel,
                stage="awareness",
                value_prop=playbook.value_proposition,
            )
            seed_audiences.append(targeting)
            creative_specs.append(creative)

            cac_low = playbook.estimated_cac * 0.7
            cac_high = playbook.estimated_cac * 1.5
            if ch_rec.cost_tier == "low":
                cac_low *= 0.5
                cac_high *= 0.7
            elif ch_rec.cost_tier == "high":
                cac_low *= 1.3
                cac_high *= 1.5

            channel_plans.append(ChannelPlan(
                channel=ch_rec.channel,
                priority=ch_rec.priority,
                recommended_budget_pct=ch_rec.recommended_budget_pct,
                targeting=targeting,
                creative=creative,
                expected_cac_range=(round(cac_low, 2), round(cac_high, 2)),
                rationale=ch_rec.rationale,
            ))

        plan = AcquisitionPlan(
            platform_id=platform_id,
            stage="cold",
            channel_plans=channel_plans,
            total_recommended_budget=None,
            estimated_cac=playbook.estimated_cac,
            seed_audiences=seed_audiences,
            creative_specs=creative_specs,
            lookalike_seeds=[],
        )
        self._plans[platform_id] = plan
        logger.info("Built cold-mode acquisition plan for platform=%s (%d channels)", platform_id, len(channel_plans))
        return plan

    def refresh_plan(
        self,
        platform_id: str,
        playbook: GrowthPlaybook,
        regions: Optional[List[str]] = None,
    ) -> AcquisitionPlan:
        plan = self.build_plan(platform_id, playbook, regions)

        if self._behavior_repo is None:
            return plan

        profiles = self._behavior_repo.list_by_application(platform_id)
        if len(profiles) < 10:
            return plan

        plan.stage = "warm"

        sorted_profiles = sorted(
            profiles,
            key=lambda p: p.rfm.total_monetary_value,
            reverse=True,
        )
        top_10pct = sorted_profiles[:max(1, len(sorted_profiles) // 10)]

        for ad_platform in ["meta", "google"]:
            plan.lookalike_seeds.append(LookalikeSpec(
                source_audience=f"top_10pct_by_ltv_{ad_platform}",
                seed_identity_ids=[p.identity_id for p in top_10pct],
                platform=ad_platform,
                similarity_pct=5,
            ))

        all_interests: Dict[str, int] = {}
        for p in profiles:
            if hasattr(p, "interests") and hasattr(p.interests, "categories"):
                for cat, count in p.interests.categories.items():
                    all_interests[cat] = all_interests.get(cat, 0) + count

        if all_interests:
            top_interests = sorted(all_interests, key=all_interests.get, reverse=True)[:10]
            for audience in plan.seed_audiences:
                for interest in top_interests:
                    if interest not in audience.interests:
                        audience.interests.append(interest)
                audience.source = "behavioral_data"

        if self._budget_allocator is not None:
            budget_plan = self._budget_allocator.get_plan(platform_id)
            if budget_plan:
                plan.total_recommended_budget = budget_plan.total_budget

        logger.info(
            "Refreshed acquisition plan for platform=%s (warm mode, %d profiles, %d lookalikes)",
            platform_id,
            len(profiles),
            len(plan.lookalike_seeds),
        )
        return plan

    def get_plan(self, platform_id: str) -> Optional[AcquisitionPlan]:
        return self._plans.get(platform_id)
