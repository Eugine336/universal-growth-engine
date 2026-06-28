"""
Cold Start Engine

Top-level orchestrator called once when a platform registers.
Classifies the platform, generates a growth playbook, auto-registers
activation policies, and produces an acquisition plan.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.decision.policy import PolicyRegistry

from .activation import ActivationPolicyGenerator
from .category import CategoryClassifier, CategoryKnowledgeBase, CategoryProfile
from .playbook import GrowthPlaybook, PlaybookGenerator

logger = logging.getLogger(__name__)


@dataclass
class ColdStartResult:
    platform_id: str
    category: CategoryProfile
    playbook: GrowthPlaybook
    policies_registered: int
    acquisition_plan: Optional[Any] = None
    ran_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ColdStartEngine:

    def __init__(
        self,
        policy_registry: PolicyRegistry,
        acquisition_engine: Optional[Any] = None,
    ):
        self._classifier = CategoryClassifier()
        self._knowledge_base = CategoryKnowledgeBase()
        self._playbook_generator = PlaybookGenerator()
        self._activation_generator = ActivationPolicyGenerator()
        self._policy_registry = policy_registry
        self._acquisition_engine = acquisition_engine
        self._results: Dict[str, ColdStartResult] = {}
        logger.info("ColdStartEngine initialized")

    def run(
        self,
        platform_id: str,
        name: str = "",
        description: str = "",
        entity_types: Optional[List[str]] = None,
        objectives: Optional[List[str]] = None,
        category_hint: str = "",
        regions: Optional[List[str]] = None,
    ) -> ColdStartResult:
        category = self._classifier.classify(
            name=name,
            description=description,
            entity_types=entity_types,
            objectives=objectives,
            category_hint=category_hint,
        )
        logger.info(
            "Classified platform=%s as category=%s (confidence=%.2f)",
            platform_id,
            category.category_id,
            category.confidence,
        )

        knowledge = self._knowledge_base.get(category.category_id)

        playbook = self._playbook_generator.generate(
            platform_id=platform_id,
            category_profile=category,
            knowledge=knowledge,
            platform_name=name,
            regions=regions,
        )

        policies = self._activation_generator.generate_policies(
            playbook=playbook,
            policy_registry=self._policy_registry,
        )
        logger.info(
            "Registered %d activation policies for platform=%s",
            len(policies),
            platform_id,
        )

        acquisition_plan = None
        if self._acquisition_engine is not None:
            acquisition_plan = self._acquisition_engine.build_plan(
                platform_id=platform_id,
                playbook=playbook,
            )

        result = ColdStartResult(
            platform_id=platform_id,
            category=category,
            playbook=playbook,
            policies_registered=len(policies),
            acquisition_plan=acquisition_plan,
        )
        self._results[platform_id] = result
        return result

    def get_result(self, platform_id: str) -> Optional[ColdStartResult]:
        return self._results.get(platform_id)

    def get_playbook(self, platform_id: str) -> Optional[GrowthPlaybook]:
        result = self._results.get(platform_id)
        return result.playbook if result else None
