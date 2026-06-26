"""
Behavior Repository

Stores and retrieves behavioral profiles.
One profile per identity per application.

In production: backed by Redis (hot cache) + Postgres (cold storage).
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from .schema import BehavioralProfile

logger = logging.getLogger(__name__)


class BehaviorRepository:

    def __init__(self):
        # key: "application_id:identity_id" → BehavioralProfile
        self._profiles: Dict[str, BehavioralProfile] = {}
        logger.info("BehaviorRepository initialized")

    def _key(self, identity_id: str, application_id: str) -> str:
        return f"{application_id}:{identity_id}"

    def save(self, profile: BehavioralProfile) -> BehavioralProfile:
        key = self._key(profile.identity_id, profile.application_id)
        self._profiles[key] = profile
        logger.debug(f"Saved behavioral profile | key={key}")
        return profile

    def get(self, identity_id: str, application_id: str) -> Optional[BehavioralProfile]:
        return self._profiles.get(self._key(identity_id, application_id))

    def get_or_create(self, identity_id: str, application_id: str) -> BehavioralProfile:
        profile = self.get(identity_id, application_id)
        if not profile:
            profile = BehavioralProfile(
                identity_id=identity_id,
                application_id=application_id,
            )
            self.save(profile)
            logger.info(
                f"Created new behavioral profile | "
                f"identity={identity_id} app={application_id}"
            )
        return profile

    def delete(self, identity_id: str, application_id: str) -> bool:
        key = self._key(identity_id, application_id)
        if key in self._profiles:
            del self._profiles[key]
            return True
        return False

    def list_by_application(self, application_id: str) -> List[BehavioralProfile]:
        return [
            p for p in self._profiles.values()
            if p.application_id == application_id
        ]

    def find_by_churn_risk(
        self,
        application_id: str,
        risk_level: str,
    ) -> List[BehavioralProfile]:
        return [
            p for p in self.list_by_application(application_id)
            if p.churn.risk_level == risk_level
        ]

    def find_by_rfm_segment(
        self,
        application_id: str,
        segment: str,
    ) -> List[BehavioralProfile]:
        return [
            p for p in self.list_by_application(application_id)
            if p.rfm.segment == segment
        ]

    def find_by_engagement_tier(
        self,
        application_id: str,
        tier: str,
    ) -> List[BehavioralProfile]:
        return [
            p for p in self.list_by_application(application_id)
            if p.engagement.tier == tier
        ]

    def find_with_intent(
        self,
        application_id: str,
        signal_type: str,
        min_strength: float = 0.5,
    ) -> List[BehavioralProfile]:
        results = []
        for p in self.list_by_application(application_id):
            signal = p.get_intent_signal(signal_type)
            if signal and signal.strength >= min_strength:
                results.append(p)
        return results

    def stats(self, application_id: Optional[str] = None) -> Dict:
        profiles = (
            self.list_by_application(application_id)
            if application_id
            else list(self._profiles.values())
        )
        tiers = {}
        segments = {}
        churn_levels = {}
        for p in profiles:
            tiers[p.engagement.tier] = tiers.get(p.engagement.tier, 0) + 1
            segments[p.rfm.segment] = segments.get(p.rfm.segment, 0) + 1
            churn_levels[p.churn.risk_level] = churn_levels.get(p.churn.risk_level, 0) + 1
        return {
            "total_profiles": len(profiles),
            "engagement_tiers": tiers,
            "rfm_segments": segments,
            "churn_risk_levels": churn_levels,
        }
