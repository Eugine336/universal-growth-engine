"""
Decision Engine

The top-level orchestrator for the decision layer.

Given an identity (and optionally a triggering event),
the engine:

1. Fetches the behavioral profile
2. Runs all predictions
3. Evaluates all active policies
4. Returns the best decision(s)
5. Stores decisions for history and learning

This is the module the action orchestrator calls.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

from core.behavior.repository import BehaviorRepository
from core.prediction.engine import PredictionEngine
from core.prediction.schema import PredictionType

from .schema import Decision, DecisionStatus
from .policy import Policy, PolicyRegistry
from .evaluator import PolicyEvaluator

logger = logging.getLogger(__name__)


class DecisionEngine:
    """
    Orchestrates the full decide loop for one identity.

    Usage:
        engine = DecisionEngine(
            behavior_repo=behavior_repo,
            prediction_engine=prediction_engine,
            policy_registry=policy_registry,
        )

        decisions = engine.decide(
            identity_id="identity_001",
            application_id="ucmc",
            trigger_event_type="PAYMENT_COMPLETED",
        )
    """

    def __init__(
        self,
        behavior_repo: BehaviorRepository,
        prediction_engine: PredictionEngine,
        policy_registry: Optional[PolicyRegistry] = None,
    ):
        self._behavior_repo = behavior_repo
        self._prediction_engine = prediction_engine
        self._registry = policy_registry or PolicyRegistry()
        self._evaluator = PolicyEvaluator(self._registry)

        # Decision history: identity_id → list of Decisions
        self._history: Dict[str, List[Decision]] = defaultdict(list)

        # Metrics
        self._total_decided: int = 0
        self._total_no_action: int = 0

        logger.info("DecisionEngine initialized")

    # ------------------------------------------------------------------
    # Policy management
    # ------------------------------------------------------------------

    def register_policy(self, policy: Policy) -> None:
        self._registry.register(policy)
        logger.info(f"Policy registered: '{policy.name}' for app '{policy.application_id}'")

    def disable_policy(self, policy_id: str) -> None:
        self._registry.disable(policy_id)

    def enable_policy(self, policy_id: str) -> None:
        self._registry.enable(policy_id)

    # ------------------------------------------------------------------
    # Core decide
    # ------------------------------------------------------------------

    def decide(
        self,
        identity_id: str,
        application_id: str,
        trigger_event_type: Optional[str] = None,
        trigger_event_id: Optional[str] = None,
        return_all: bool = False,
    ) -> List[Decision]:
        """
        Run the full decide loop for one identity.

        Returns a list of decisions sorted by priority.
        If return_all=False (default), returns only the top decision.
        Returns empty list if no policies matched or no profile exists.
        """
        # 1. Fetch behavioral profile
        profile = self._behavior_repo.get(identity_id, application_id)
        if not profile:
            logger.warning(
                f"No behavioral profile for identity={identity_id} "
                f"app={application_id} — cannot decide"
            )
            return []

        # 2. Run predictions
        prediction_set = self._prediction_engine.predict_from_profile(profile)

        # 3. Fetch decision history for this identity
        history = self._history.get(identity_id, [])

        # 4. Evaluate policies
        decisions = self._evaluator.evaluate(
            profile=profile,
            prediction_set=prediction_set,
            trigger_event_type=trigger_event_type,
            decision_history=history,
            trigger_event_id=trigger_event_id,
        )

        # 5. Store decisions in history
        for decision in decisions:
            self._history[identity_id].append(decision)
            self._total_decided += 1

        if not decisions:
            self._total_no_action += 1
            logger.debug(
                f"No action decided | identity={identity_id} "
                f"trigger={trigger_event_type}"
            )

        if return_all:
            return decisions
        return decisions[:1]

    def decide_best(
        self,
        identity_id: str,
        application_id: str,
        trigger_event_type: Optional[str] = None,
        trigger_event_id: Optional[str] = None,
    ) -> Optional[Decision]:
        """Return only the single best decision, or None."""
        decisions = self.decide(
            identity_id=identity_id,
            application_id=application_id,
            trigger_event_type=trigger_event_type,
            trigger_event_id=trigger_event_id,
            return_all=False,
        )
        return decisions[0] if decisions else None

    def decide_batch(
        self,
        application_id: str,
        trigger_event_type: Optional[str] = None,
    ) -> Dict[str, Optional[Decision]]:
        """
        Run decide for all identities with behavioral profiles in an application.
        Returns a dict of identity_id → best Decision (or None).
        """
        profiles = self._behavior_repo.list_by_application(application_id)
        results = {}
        for profile in profiles:
            decision = self.decide_best(
                identity_id=profile.identity_id,
                application_id=application_id,
                trigger_event_type=trigger_event_type,
            )
            results[profile.identity_id] = decision

        logger.info(
            f"Batch decide complete | app={application_id} "
            f"identities={len(profiles)} "
            f"with_action={sum(1 for d in results.values() if d)}"
        )
        return results

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def get_history(
        self,
        identity_id: str,
        application_id: Optional[str] = None,
        status: Optional[DecisionStatus] = None,
        limit: int = 50,
    ) -> List[Decision]:
        history = self._history.get(identity_id, [])
        if application_id:
            history = [d for d in history if d.application_id == application_id]
        if status:
            history = [d for d in history if d.status == status]
        return history[-limit:]

    def mark_executed(
        self,
        decision_id: str,
        identity_id: str,
        success: bool = True,
        error: Optional[str] = None,
    ) -> Optional[Decision]:
        """Mark a decision as executed (called by the action orchestrator)."""
        from .schema import DecisionOutcome
        history = self._history.get(identity_id, [])
        for decision in history:
            if decision.id == decision_id:
                outcome = DecisionOutcome(
                    executed_at=datetime.now(timezone.utc),
                    success=success,
                    error=error,
                )
                decision.mark_executed(outcome)
                return decision
        return None

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def stats(self) -> Dict:
        total_history = sum(len(v) for v in self._history.values())
        return {
            "total_decided": self._total_decided,
            "total_no_action": self._total_no_action,
            "identities_with_history": len(self._history),
            "total_decisions_in_history": total_history,
            "registered_policies": self._registry.count(),
        }
