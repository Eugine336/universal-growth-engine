"""
Admin Manager

System-level administration: health checks, platform listing,
and configuration management.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .schema import PlatformConfigUpdate, SystemHealth

logger = logging.getLogger(__name__)


class AdminManager:

    def __init__(self, pipeline: Any):
        self._pipeline = pipeline
        logger.info("AdminManager initialized")

    def get_system_health(self) -> SystemHealth:
        p = self._pipeline
        components: Dict[str, str] = {}

        identity_stats = {}
        if p.identity_graph:
            components["identity_graph"] = "healthy"
            identity_stats = p.identity_graph.stats()
        if p.behavior_repo:
            components["behavior_repo"] = "healthy"
        if p.prediction_engine:
            components["prediction_engine"] = "healthy"
        if p.experimentation_engine:
            components["experimentation_engine"] = "healthy"
        if p.referral_engine:
            components["referral_engine"] = "healthy"
        if p.audience_engine:
            components["audience_engine"] = "healthy"
        if p.event_bus:
            components["event_bus"] = "healthy"
        if p.cross_platform_manager:
            components["cross_platform_manager"] = "healthy"

        behavior_stats = p.behavior_repo.stats() if p.behavior_repo else {}
        exp_stats = (
            p.experimentation_engine.stats() if p.experimentation_engine else {}
        )
        audience_stats = p.audience_engine.stats() if p.audience_engine else {}
        referral_stats = p.referral_engine.stats() if p.referral_engine else {}

        return SystemHealth(
            total_platforms=(
                len(p.platform_registry._platforms)
                if p.platform_registry
                else 0
            ),
            total_identities=identity_stats.get("total_identities", 0),
            total_profiles=behavior_stats.get("total_profiles", 0),
            total_experiments=exp_stats.get("total_experiments", 0),
            total_audiences=audience_stats.get("total_audiences", 0),
            total_referral_programs=referral_stats.get("total_programs", 0),
            components=components,
        )

    def list_platforms_summary(self) -> List[Dict[str, Any]]:
        p = self._pipeline
        if not p.platform_registry:
            return []
        platforms = p.platform_registry.list_platforms()
        results = []
        for plat in platforms:
            profile_count = 0
            if p.behavior_repo:
                profile_count = len(
                    p.behavior_repo.list_by_application(plat.id)
                )
            results.append(
                {
                    "id": plat.id,
                    "name": plat.name,
                    "slug": plat.slug,
                    "status": plat.status.value,
                    "profile_count": profile_count,
                    "created_at": plat.created_at.isoformat(),
                }
            )
        return results

    def get_platform_detail(self, platform_id: str) -> Optional[Dict[str, Any]]:
        p = self._pipeline
        if not p.platform_registry:
            return None
        plat = p.platform_registry.get_by_id(platform_id)
        if not plat:
            return None

        profile_count = 0
        if p.behavior_repo:
            profile_count = len(
                p.behavior_repo.list_by_application(platform_id)
            )

        identity_count = 0
        if p.identity_graph:
            identity_count = len(
                p.identity_graph.list_by_application(platform_id)
            )

        audience_count = 0
        if p.audience_engine:
            audience_count = len(
                p.audience_engine.list_audiences(platform_id)
            )

        return {
            "id": plat.id,
            "name": plat.name,
            "slug": plat.slug,
            "status": plat.status.value,
            "quotas": plat.quotas.model_dump() if plat.quotas else {},
            "metadata": plat.metadata,
            "profile_count": profile_count,
            "identity_count": identity_count,
            "audience_count": audience_count,
            "created_at": plat.created_at.isoformat(),
            "updated_at": plat.updated_at.isoformat(),
        }

    def update_platform_config(
        self, platform_id: str, updates: PlatformConfigUpdate
    ) -> Optional[Dict[str, Any]]:
        p = self._pipeline
        if not p.platform_registry:
            return None
        plat = p.platform_registry.get_by_id(platform_id)
        if not plat:
            return None

        if updates.name is not None:
            plat.name = updates.name
        if updates.metadata is not None:
            plat.metadata.update(updates.metadata)

        return self.get_platform_detail(platform_id)

    def get_event_bus_stats(self) -> Dict[str, Any]:
        p = self._pipeline
        if not p.event_bus:
            return {}
        return p.event_bus.stats()
