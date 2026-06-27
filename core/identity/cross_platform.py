"""
Cross-Platform Identity Management

Links the same real person across multiple platforms on UGIE.
When Platform A and Platform B both have a user with the same email,
UGIE knows they're the same person — enabling cross-platform behavioral
merge, cross-promotion, and seed audience sharing.

Consent-driven: platforms must explicitly opt in to cross-platform linking.
Privacy-first: linking values are stored as SHA256 hashes, never raw.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .graph import IdentityGraph
from .schema import Identity
from core.behavior.repository import BehaviorRepository
from core.behavior.schema import BehavioralProfile

logger = logging.getLogger(__name__)


class CrossPlatformConfig(BaseModel):
    """Per-platform configuration for cross-platform identity linking."""

    platform_id: str
    allow_cross_platform_linking: bool = False
    share_behavioral_data: bool = False
    allowed_partner_platforms: List[str] = Field(default_factory=list)
    linkable_touchpoint_types: List[str] = Field(
        default_factory=lambda: ["email", "phone"]
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class CrossPlatformLink(BaseModel):
    """Record of a confirmed cross-platform identity link."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    identity_id: str
    platform_ids: List[str] = Field(default_factory=list)
    link_type: str  # "email" | "phone" | "device"
    link_value_hash: str
    consent_status: str = "auto"  # "auto" | "confirmed"
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CrossPlatformManager:
    """
    Manages cross-platform identity linking, consent, and profile aggregation.

    Usage:
        manager = CrossPlatformManager(identity_graph, behavior_repo)
        manager.set_platform_config(CrossPlatformConfig(
            platform_id="ucmc",
            allow_cross_platform_linking=True,
            share_behavioral_data=True,
        ))
    """

    def __init__(
        self,
        identity_graph: IdentityGraph,
        behavior_repo: BehaviorRepository,
    ):
        self._graph = identity_graph
        self._behavior_repo = behavior_repo
        self._configs: Dict[str, CrossPlatformConfig] = {}
        self._links: Dict[str, CrossPlatformLink] = {}
        # identity_id → link_id for fast lookup
        self._identity_links: Dict[str, List[str]] = {}
        logger.info("CrossPlatformManager initialized")

    # ------------------------------------------------------------------
    # Config management
    # ------------------------------------------------------------------

    def set_platform_config(
        self, config: CrossPlatformConfig
    ) -> CrossPlatformConfig:
        config.updated_at = datetime.now(timezone.utc)
        self._configs[config.platform_id] = config
        logger.info(
            f"Cross-platform config set | platform={config.platform_id} "
            f"linking={config.allow_cross_platform_linking} "
            f"sharing={config.share_behavioral_data}"
        )
        return config

    def get_platform_config(
        self, platform_id: str
    ) -> Optional[CrossPlatformConfig]:
        return self._configs.get(platform_id)

    # ------------------------------------------------------------------
    # Cross-platform identity discovery
    # ------------------------------------------------------------------

    def find_cross_platform_identities(
        self, platform_id: str
    ) -> List[Dict[str, Any]]:
        """Find identities that exist on this platform AND at least one other."""
        results = []
        identities = self._graph.list_by_application(platform_id)

        for identity in identities:
            if identity.is_merged():
                continue
            other_platforms = [
                app_id
                for app_id in identity.application_ids
                if app_id != platform_id
            ]
            if other_platforms:
                tp_types = set()
                for tp in identity.touchpoints:
                    for app_id in other_platforms:
                        if app_id in identity.application_ids:
                            tp_types.add(tp.type.value)
                results.append(
                    {
                        "identity_id": identity.id,
                        "platforms": identity.application_ids[:],
                        "touchpoint_overlap": sorted(tp_types),
                    }
                )
        return results

    def get_cross_platform_profile(
        self, identity_id: str, requesting_platform_id: str
    ) -> Optional[Dict[str, Any]]:
        """Aggregated behavioral view across platforms the requester can see."""
        identity = self._graph.get(identity_id)
        if not identity or identity.is_merged():
            return None

        profiles: List[BehavioralProfile] = []
        for app_id in identity.application_ids:
            if not self._check_sharing_allowed(app_id, requesting_platform_id):
                continue
            profile = self._behavior_repo.get(identity_id, app_id)
            if profile:
                profiles.append(profile)

        if not profiles:
            return None

        merged = self._merge_profiles(profiles)
        merged["identity_id"] = identity_id
        merged["platforms"] = [p.application_id for p in profiles]
        merged["canonical_email"] = identity.canonical_email
        return merged

    def get_shared_identities(
        self, platform_a_id: str, platform_b_id: str
    ) -> List[Identity]:
        """Identities that appear on BOTH platforms."""
        results = []
        for identity in self._graph.list_by_application(platform_a_id):
            if identity.is_merged():
                continue
            if platform_b_id in identity.application_ids:
                results.append(identity)
        return results

    def get_cross_promotion_candidates(
        self,
        source_platform_id: str,
        target_platform_id: str,
        min_engagement_tier: str = "warming",
    ) -> List[Dict[str, Any]]:
        """
        Identities on source that are NOT on target, filtered by engagement.
        These are people source platform could promote target platform to.
        """
        tier_order = {"cold": 0, "warming": 1, "active": 2, "power": 3}
        min_tier_val = tier_order.get(min_engagement_tier, 1)

        candidates = []
        for identity in self._graph.list_by_application(source_platform_id):
            if identity.is_merged():
                continue
            if target_platform_id in identity.application_ids:
                continue

            profile = self._behavior_repo.get(
                identity.id, source_platform_id
            )
            if not profile:
                continue

            tier_val = tier_order.get(profile.engagement.tier, 0)
            if tier_val < min_tier_val:
                continue

            sharing_ok = self._check_sharing_allowed(
                source_platform_id, target_platform_id
            )
            candidates.append(
                {
                    "identity_id": identity.id,
                    "canonical_email": (
                        identity.canonical_email if sharing_ok else None
                    ),
                    "engagement_tier": profile.engagement.tier,
                    "rfm_segment": profile.rfm.segment,
                    "total_sessions": profile.engagement.total_sessions,
                }
            )
        return candidates

    # ------------------------------------------------------------------
    # Link management
    # ------------------------------------------------------------------

    def record_link(
        self,
        identity_id: str,
        platform_ids: List[str],
        link_type: str,
        link_value: str,
    ) -> CrossPlatformLink:
        """Record a cross-platform link for an identity."""
        link = CrossPlatformLink(
            identity_id=identity_id,
            platform_ids=sorted(platform_ids),
            link_type=link_type,
            link_value_hash=self._hash_value(link_value),
            consent_status="auto",
        )
        self._links[link.id] = link
        if identity_id not in self._identity_links:
            self._identity_links[identity_id] = []
        self._identity_links[identity_id].append(link.id)

        logger.info(
            f"Cross-platform link recorded | identity={identity_id} "
            f"platforms={platform_ids} type={link_type}"
        )
        return link

    def get_links_for_identity(
        self, identity_id: str
    ) -> List[CrossPlatformLink]:
        link_ids = self._identity_links.get(identity_id, [])
        return [
            self._links[lid] for lid in link_ids if lid in self._links
        ]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> Dict[str, Any]:
        configs_enabled = sum(
            1 for c in self._configs.values() if c.allow_cross_platform_linking
        )
        sharing_enabled = sum(
            1 for c in self._configs.values() if c.share_behavioral_data
        )

        linked_identities = set()
        for link in self._links.values():
            linked_identities.add(link.identity_id)

        return {
            "total_configs": len(self._configs),
            "linking_enabled_platforms": configs_enabled,
            "sharing_enabled_platforms": sharing_enabled,
            "total_links": len(self._links),
            "unique_linked_identities": len(linked_identities),
        }

    # ------------------------------------------------------------------
    # Consent / sharing checks
    # ------------------------------------------------------------------

    def _check_sharing_allowed(
        self, source_platform_id: str, requesting_platform_id: str
    ) -> bool:
        """Check if source platform allows sharing with requesting platform."""
        if source_platform_id == requesting_platform_id:
            return True

        config = self._configs.get(source_platform_id)
        if not config:
            return False
        if not config.share_behavioral_data:
            return False
        if config.allowed_partner_platforms:
            return requesting_platform_id in config.allowed_partner_platforms
        return True

    def is_linking_enabled(self, platform_id: str) -> bool:
        config = self._configs.get(platform_id)
        return config.allow_cross_platform_linking if config else False

    # ------------------------------------------------------------------
    # Profile aggregation
    # ------------------------------------------------------------------

    def _merge_profiles(
        self, profiles: List[BehavioralProfile]
    ) -> Dict[str, Any]:
        """Merge multiple per-platform profiles into one aggregated view."""
        total_sessions = 0
        total_events = 0
        total_conversions = 0
        total_monetary = 0.0
        all_interests: Dict[str, int] = {}
        all_event_counts: Dict[str, int] = {}
        highest_tier = "cold"
        tier_order = {"cold": 0, "warming": 1, "active": 2, "power": 3}

        for p in profiles:
            total_sessions += p.engagement.total_sessions
            total_events += p.engagement.total_events
            total_conversions += p.rfm.total_conversions
            total_monetary += p.rfm.total_monetary_value

            for cat, count in p.interests.category_interests.items():
                all_interests[cat] = all_interests.get(cat, 0) + count

            for evt, count in p.event_counts.items():
                all_event_counts[evt] = all_event_counts.get(evt, 0) + count

            if tier_order.get(p.engagement.tier, 0) > tier_order.get(
                highest_tier, 0
            ):
                highest_tier = p.engagement.tier

        top_interests = sorted(
            all_interests.keys(),
            key=lambda k: all_interests[k],
            reverse=True,
        )[:10]

        return {
            "total_sessions": total_sessions,
            "total_events": total_events,
            "total_conversions": total_conversions,
            "total_monetary_value": total_monetary,
            "highest_engagement_tier": highest_tier,
            "combined_interests": all_interests,
            "top_interests": top_interests,
            "combined_event_counts": all_event_counts,
            "profile_count": len(profiles),
        }

    @staticmethod
    def _hash_value(value: str) -> str:
        return hashlib.sha256(value.lower().strip().encode()).hexdigest()
