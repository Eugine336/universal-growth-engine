"""
Action Orchestrator

The orchestrator is the final step in the UGIE pipeline.

It:
1. Receives a Decision from the decision engine
2. Converts it into an Action
3. Resolves the correct connector
4. Dispatches the action to the connector
5. Records the result
6. Publishes a feedback event back into the event bus
   (closing the learning loop)
7. Handles retries on transient failures

The orchestrator never executes actions directly.
It only delegates — connectors do the real work.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from core.decision.schema import Decision, DecisionStatus, DecisionOutcome

from .schema import Action, ActionStatus, ActionResult, ConnectorManifest
from .connector import BaseConnector, ConnectorRegistry

logger = logging.getLogger(__name__)

# Feedback event publisher type — injected to avoid circular imports
FeedbackPublisher = Callable[[str, str, dict], None]


class DispatchResult:
    """Result of dispatching one decision through the orchestrator."""

    def __init__(
        self,
        action: Action,
        result: ActionResult,
        decision: Decision,
    ):
        self.action = action
        self.result = result
        self.decision = decision
        self.success = result.success

    def __repr__(self):
        return (
            f"DispatchResult(action={self.action.id[:8]}, "
            f"success={self.success}, "
            f"connector={self.result.connector_id})"
        )


class ActionOrchestrator:
    """
    Routes decisions to connectors and closes the feedback loop.

    Usage:
        orchestrator = ActionOrchestrator(connector_registry)

        # Optional: attach feedback publisher (event bus)
        orchestrator.set_feedback_publisher(event_bus.publish_feedback)

        # Dispatch a single decision
        result = orchestrator.dispatch(decision)

        # Dispatch a batch
        results = orchestrator.dispatch_batch(decisions)
    """

    def __init__(
        self,
        connector_registry: Optional[ConnectorRegistry] = None,
        feedback_publisher: Optional[FeedbackPublisher] = None,
    ):
        self._registry = connector_registry or ConnectorRegistry()
        self._feedback_publisher = feedback_publisher

        # Action store: action_id → Action
        self._actions: Dict[str, Action] = {}

        # Index: identity_id → [action_ids]
        self._by_identity: Dict[str, List[str]] = defaultdict(list)

        # Metrics
        self._total_dispatched: int = 0
        self._total_succeeded: int = 0
        self._total_failed: int = 0
        self._total_retried: int = 0

        logger.info("ActionOrchestrator initialized")

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_feedback_publisher(self, publisher: FeedbackPublisher) -> None:
        self._feedback_publisher = publisher

    def register_connector(self, connector: BaseConnector) -> None:
        self._registry.register(connector)

    # ------------------------------------------------------------------
    # Core dispatch
    # ------------------------------------------------------------------

    def dispatch(self, decision: Decision) -> DispatchResult:
        """
        Dispatch a single decision.

        Pipeline:
        convert → resolve connector → execute → record → feedback
        """
        # 1. Convert decision to action
        action = self._decision_to_action(decision)
        self._store_action(action)

        # 2. Resolve connector
        connector = self._registry.resolve(action.action_type)
        if not connector:
            error = f"No connector for action type '{action.action_type}'"
            logger.warning(error)
            result = ActionResult(
                success=False,
                connector_id="none",
                error=error,
            )
            action.record_attempt(result)
            self._total_failed += 1
            return DispatchResult(action=action, result=result, decision=decision)

        # 3. Execute (with retry)
        result = self._execute_with_retry(action, connector)

        # 4. Update decision outcome
        outcome = DecisionOutcome(
            executed_at=datetime.now(timezone.utc),
            connector_id=connector.manifest.id,
            connector_response=result.response,
            success=result.success,
            error=result.error,
        )
        decision.mark_executed(outcome)

        # 5. Publish feedback event
        if self._feedback_publisher and result.success:
            self._publish_feedback(action, result)

        # 6. Update metrics
        if result.success:
            self._total_succeeded += 1
        else:
            self._total_failed += 1
        self._total_dispatched += 1

        logger.info(
            f"Dispatched | action={action.id[:8]} "
            f"type={action.action_type} "
            f"connector={connector.manifest.id} "
            f"success={result.success} "
            f"attempts={action.attempts}"
        )

        return DispatchResult(action=action, result=result, decision=decision)

    def dispatch_batch(self, decisions: List[Decision]) -> List[DispatchResult]:
        """Dispatch a list of decisions. Returns one DispatchResult per decision."""
        results = []
        for decision in decisions:
            if not decision.is_executable():
                logger.debug(f"Skipping non-executable decision {decision.id[:8]}")
                continue
            results.append(self.dispatch(decision))
        return results

    # ------------------------------------------------------------------
    # Retry logic
    # ------------------------------------------------------------------

    def _execute_with_retry(
        self,
        action: Action,
        connector: BaseConnector,
    ) -> ActionResult:
        """Execute the action with up to max_attempts retries."""
        last_result = None

        while action.can_retry() and action.status in (
            ActionStatus.QUEUED, ActionStatus.RETRYING
        ):
            t0 = time.time()
            try:
                action.dispatched_at = datetime.now(timezone.utc)
                action.status = ActionStatus.DISPATCHED
                result = connector.execute(action)
                result.duration_ms = (time.time() - t0) * 1000
            except Exception as e:
                result = ActionResult(
                    success=False,
                    connector_id=connector.manifest.id,
                    error=f"Unhandled connector exception: {str(e)}",
                    duration_ms=(time.time() - t0) * 1000,
                )

            action.record_attempt(result)
            last_result = result

            if result.success:
                break

            if action.status == ActionStatus.RETRYING:
                self._total_retried += 1
                logger.warning(
                    f"Retrying action {action.id[:8]} "
                    f"(attempt {action.attempts}/{action.max_attempts}) "
                    f"error={result.error}"
                )

        return last_result

    # ------------------------------------------------------------------
    # Feedback loop
    # ------------------------------------------------------------------

    def _publish_feedback(self, action: Action, result: ActionResult) -> None:
        """
        Publish a feedback event back into the event bus.
        This closes the learning loop — outcomes feed back into behavior profiles.
        """
        try:
            feedback_payload = {
                "action_id": action.id,
                "action_type": action.action_type,
                "connector_id": result.connector_id,
                "connector_ref": result.connector_ref,
                "identity_id": action.identity_id,
                "application_id": action.application_id,
                "success": result.success,
                "context": action.context,
            }
            self._feedback_publisher(
                action.application_id,
                "ACTION_EXECUTED",
                feedback_payload,
            )
            logger.debug(
                f"Feedback published | action={action.id[:8]} "
                f"type={action.action_type}"
            )
        except Exception as e:
            logger.error(f"Failed to publish feedback for action {action.id}: {e}")

    # ------------------------------------------------------------------
    # Action management
    # ------------------------------------------------------------------

    def get_action(self, action_id: str) -> Optional[Action]:
        return self._actions.get(action_id)

    def get_actions_for_identity(
        self,
        identity_id: str,
        status: Optional[ActionStatus] = None,
    ) -> List[Action]:
        ids = self._by_identity.get(identity_id, [])
        actions = [self._actions[i] for i in ids if i in self._actions]
        if status:
            actions = [a for a in actions if a.status == status]
        return actions

    def record_feedback(
        self,
        action_id: str,
        event: str,
        data: Optional[dict] = None,
    ) -> Optional[Action]:
        """
        Record downstream feedback on an executed action.
        e.g. email opened, link clicked, converted.
        """
        action = self._actions.get(action_id)
        if not action:
            return None
        action.feedback[event] = {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            **(data or {}),
        }
        logger.info(f"Feedback recorded | action={action_id[:8]} event={event}")
        return action

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _decision_to_action(self, decision: Decision) -> Action:
        """Convert a Decision into an Action."""
        return Action(
            decision_id=decision.id,
            identity_id=decision.identity_id,
            application_id=decision.application_id,
            action_type=decision.action_type.value,
            channel=decision.channel,
            payload=dict(decision.payload),
            execute_after=decision.execute_after,
            valid_until=decision.valid_until,
            context={
                "policy_id": decision.context.policy_id,
                "policy_name": decision.context.policy_name,
                "churn_score": decision.context.churn_score,
                "fraud_score": decision.context.fraud_score,
                "engagement_tier": decision.context.engagement_tier,
                "rfm_segment": decision.context.rfm_segment,
                "trigger_event_type": decision.context.trigger_event_type,
            },
        )

    def _store_action(self, action: Action) -> None:
        self._actions[action.id] = action
        self._by_identity[action.identity_id].append(action.id)

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def stats(self) -> Dict:
        status_counts: Dict[str, int] = defaultdict(int)
        for action in self._actions.values():
            status_counts[action.status.value] += 1

        return {
            "total_dispatched": self._total_dispatched,
            "total_succeeded": self._total_succeeded,
            "total_failed": self._total_failed,
            "total_retried": self._total_retried,
            "success_rate": (
                round(self._total_succeeded / self._total_dispatched, 4)
                if self._total_dispatched > 0 else None
            ),
            "actions_in_store": len(self._actions),
            "by_status": dict(status_counts),
            "connectors": [c.id for c in self._registry.list_connectors()],
        }
