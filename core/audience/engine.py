"""
Audience Engine

Creates, stores, and evaluates audiences against behavioral profiles.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.behavior.repository import BehaviorRepository
from core.behavior.schema import BehavioralProfile

from .schema import Audience, AudienceDefinition, AudienceRule, AudienceRuleGroup

logger = logging.getLogger(__name__)


class AudienceEngine:

    def __init__(self, behavior_repo: BehaviorRepository):
        self._behavior_repo = behavior_repo
        self._audiences: Dict[str, Audience] = {}
        logger.info("AudienceEngine initialized")

    def create_audience(
        self,
        platform_id: str,
        definition: AudienceDefinition,
    ) -> Audience:
        audience = Audience(
            platform_id=platform_id,
            definition=definition,
            status="active",
        )
        self._audiences[audience.id] = audience
        logger.info(
            f"Created audience '{definition.name}' | id={audience.id} "
            f"platform={platform_id}"
        )
        return audience

    def get_audience(self, audience_id: str) -> Optional[Audience]:
        return self._audiences.get(audience_id)

    def list_audiences(self, platform_id: str) -> List[Audience]:
        return [
            a for a in self._audiences.values()
            if a.platform_id == platform_id and a.status != "archived"
        ]

    def update_audience(
        self,
        audience_id: str,
        definition: AudienceDefinition,
    ) -> Optional[Audience]:
        audience = self._audiences.get(audience_id)
        if not audience:
            return None
        audience.definition = definition
        audience.updated_at = datetime.now(timezone.utc)
        return audience

    def archive_audience(self, audience_id: str) -> Optional[Audience]:
        audience = self._audiences.get(audience_id)
        if not audience:
            return None
        audience.status = "archived"
        audience.updated_at = datetime.now(timezone.utc)
        return audience

    def evaluate(self, audience_id: str) -> List[BehavioralProfile]:
        audience = self._audiences.get(audience_id)
        if not audience:
            return []
        all_profiles = list(self._behavior_repo._profiles.values())
        matches = [
            p for p in all_profiles
            if self._evaluate_rules(p, audience.definition)
        ]
        audience.member_count = len(matches)
        audience.last_evaluated_at = datetime.now(timezone.utc)
        return matches

    def preview(
        self,
        platform_id: str,
        definition: AudienceDefinition,
    ) -> dict:
        all_profiles = list(self._behavior_repo._profiles.values())
        matches = [
            p for p in all_profiles
            if self._evaluate_rules(p, definition)
        ]
        return {
            "matching_count": len(matches),
            "sample_identity_ids": [p.identity_id for p in matches[:10]],
        }

    def _evaluate_rules(
        self,
        profile: BehavioralProfile,
        definition: AudienceDefinition,
    ) -> bool:
        if not definition.groups:
            return True
        return all(
            self._evaluate_group(profile, group)
            for group in definition.groups
        )

    def _evaluate_group(
        self,
        profile: BehavioralProfile,
        group: AudienceRuleGroup,
    ) -> bool:
        if not group.rules:
            return True
        results = [self._evaluate_rule(profile, rule) for rule in group.rules]
        if group.operator == "OR":
            return any(results)
        return all(results)

    def _evaluate_rule(
        self,
        profile: BehavioralProfile,
        rule: AudienceRule,
    ) -> bool:
        value = self._get_field_value(profile, rule.field)
        op = rule.operator

        if op == "exists":
            return value is not None
        if value is None:
            return False

        if op == "eq":
            return value == rule.value
        if op == "neq":
            return value != rule.value
        if op == "gt":
            return value > rule.value
        if op == "gte":
            return value >= rule.value
        if op == "lt":
            return value < rule.value
        if op == "lte":
            return value <= rule.value
        if op == "in":
            return value in (rule.value or [])
        if op == "not_in":
            return value not in (rule.value or [])
        if op == "contains":
            if isinstance(value, str):
                return rule.value in value
            if isinstance(value, (list, dict)):
                return rule.value in value
            return False

        return False

    def _get_field_value(self, profile: BehavioralProfile, field_path: str) -> Any:
        parts = field_path.split(".")
        current: Any = profile
        for part in parts:
            if current is None:
                return None
            if isinstance(current, dict):
                current = current.get(part)
            elif hasattr(current, part):
                current = getattr(current, part)
            else:
                return None
        return current

    def stats(self) -> dict:
        by_status: Dict[str, int] = {}
        for a in self._audiences.values():
            by_status[a.status] = by_status.get(a.status, 0) + 1
        return {
            "total_audiences": len(self._audiences),
            "by_status": by_status,
        }
