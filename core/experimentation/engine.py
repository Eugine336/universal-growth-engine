"""
Experimentation Engine

Assigns identities to experiment variants and modifies decisions accordingly.

Called by the DecisionEngine AFTER a policy matches but BEFORE the decision
is finalized.

Assignment is deterministic: hash(experiment_id + identity_id) → bucket → variant.
This ensures the same identity always gets the same variant (sticky assignment).
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.decision.schema import Decision

from .schema import (
    Experiment,
    ExperimentAssignment,
    ExperimentStatus,
    ExperimentVariant,
)

logger = logging.getLogger(__name__)


class ExperimentationEngine:

    def __init__(self):
        self._experiments: Dict[str, Experiment] = {}
        self._assignments: Dict[str, ExperimentAssignment] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, experiment: Experiment) -> None:
        self._experiments[experiment.id] = experiment
        logger.info(
            f"Experiment registered: '{experiment.name}' "
            f"targeting policy={experiment.target_policy_id}"
        )

    def get(self, experiment_id: str) -> Optional[Experiment]:
        return self._experiments.get(experiment_id)

    def list_experiments(
        self,
        application_id: Optional[str] = None,
        status: Optional[ExperimentStatus] = None,
    ) -> List[Experiment]:
        results = list(self._experiments.values())
        if application_id:
            results = [e for e in results if e.application_id == application_id]
        if status:
            results = [e for e in results if e.status == status]
        return results

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, experiment_id: str) -> Optional[Experiment]:
        exp = self._experiments.get(experiment_id)
        if exp and exp.status in (ExperimentStatus.DRAFT, ExperimentStatus.PAUSED):
            exp.status = ExperimentStatus.RUNNING
            if not exp.starts_at:
                exp.starts_at = datetime.now(timezone.utc)
        return exp

    def pause(self, experiment_id: str) -> Optional[Experiment]:
        exp = self._experiments.get(experiment_id)
        if exp and exp.status == ExperimentStatus.RUNNING:
            exp.status = ExperimentStatus.PAUSED
        return exp

    def complete(self, experiment_id: str) -> Optional[Experiment]:
        exp = self._experiments.get(experiment_id)
        if exp and exp.status in (ExperimentStatus.RUNNING, ExperimentStatus.PAUSED):
            exp.status = ExperimentStatus.COMPLETED
            exp.ends_at = datetime.now(timezone.utc)
        return exp

    # ------------------------------------------------------------------
    # Policy lookup
    # ------------------------------------------------------------------

    def get_active_for_policy(
        self,
        policy_id: str,
        application_id: str,
    ) -> Optional[Experiment]:
        now = datetime.now(timezone.utc)
        for exp in self._experiments.values():
            if exp.status != ExperimentStatus.RUNNING:
                continue
            if exp.target_policy_id != policy_id:
                continue
            if exp.application_id != application_id and exp.application_id != "*":
                continue
            if exp.ends_at and now > exp.ends_at:
                continue
            return exp
        return None

    # ------------------------------------------------------------------
    # Assignment
    # ------------------------------------------------------------------

    def assign(
        self,
        experiment: Experiment,
        identity_id: str,
    ) -> ExperimentAssignment:
        key = f"{experiment.id}:{identity_id}"
        if key in self._assignments:
            return self._assignments[key]

        bucket = self._hash_bucket(experiment.id, identity_id)

        cumulative = 0.0
        assigned_variant = experiment.variants[-1]
        for variant in experiment.variants:
            cumulative += variant.weight
            if bucket < cumulative:
                assigned_variant = variant
                break

        assignment = ExperimentAssignment(
            experiment_id=experiment.id,
            variant_id=assigned_variant.id,
            identity_id=identity_id,
        )
        self._assignments[key] = assignment
        experiment.variant_counts[assigned_variant.id] = (
            experiment.variant_counts.get(assigned_variant.id, 0) + 1
        )
        return assignment

    # ------------------------------------------------------------------
    # Targeting
    # ------------------------------------------------------------------

    def matches_targeting(
        self,
        experiment: Experiment,
        rfm_segment: Optional[str],
        engagement_tier: Optional[str],
    ) -> bool:
        if experiment.target_rfm_segments:
            if rfm_segment not in experiment.target_rfm_segments:
                return False
        if experiment.target_engagement_tiers:
            if engagement_tier not in experiment.target_engagement_tiers:
                return False
        return True

    # ------------------------------------------------------------------
    # Variant application
    # ------------------------------------------------------------------

    def apply_variant(
        self,
        decision: Decision,
        assignment: ExperimentAssignment,
        experiment: Experiment,
    ) -> Decision:
        decision.experiment_id = experiment.id
        decision.variant_id = assignment.variant_id

        variant = next(
            (v for v in experiment.variants if v.id == assignment.variant_id),
            None,
        )
        if variant:
            for key, value in variant.policy_overrides.items():
                self._set_nested(decision, key, value)

        return decision

    # ------------------------------------------------------------------
    # Conversion tracking
    # ------------------------------------------------------------------

    def record_conversion(self, experiment_id: str, identity_id: str) -> bool:
        key = f"{experiment_id}:{identity_id}"
        assignment = self._assignments.get(key)
        if not assignment:
            return False
        exp = self._experiments.get(experiment_id)
        if not exp:
            return False
        exp.variant_conversions[assignment.variant_id] = (
            exp.variant_conversions.get(assignment.variant_id, 0) + 1
        )
        return True

    def get_results(self, experiment_id: str) -> Dict[str, Any]:
        exp = self._experiments.get(experiment_id)
        if not exp:
            return {}

        results: Dict[str, Any] = {
            "experiment_id": exp.id,
            "name": exp.name,
            "status": exp.status.value,
            "variants": {},
        }
        for variant in exp.variants:
            count = exp.variant_counts.get(variant.id, 0)
            conversions = exp.variant_conversions.get(variant.id, 0)
            results["variants"][variant.id] = {
                "name": variant.name,
                "weight": variant.weight,
                "assignments": count,
                "conversions": conversions,
                "conversion_rate": (
                    round(conversions / count, 4) if count > 0 else 0.0
                ),
            }
        return results

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def stats(self) -> Dict[str, Any]:
        by_status: Dict[str, int] = {}
        for exp in self._experiments.values():
            by_status[exp.status.value] = by_status.get(exp.status.value, 0) + 1
        return {
            "total_experiments": len(self._experiments),
            "total_assignments": len(self._assignments),
            "by_status": by_status,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _hash_bucket(experiment_id: str, identity_id: str) -> float:
        hash_input = f"{experiment_id}:{identity_id}"
        digest = hashlib.sha256(hash_input.encode()).hexdigest()
        return int(digest, 16) % 10000 / 10000.0

    @staticmethod
    def _set_nested(obj: Any, dotted_key: str, value: Any) -> None:
        parts = dotted_key.split(".")
        target = obj
        for part in parts[:-1]:
            if isinstance(target, dict):
                target = target.setdefault(part, {})
            elif hasattr(target, part):
                target = getattr(target, part)
            else:
                return
        final = parts[-1]
        if isinstance(target, dict):
            target[final] = value
        elif hasattr(target, final):
            setattr(target, final, value)
