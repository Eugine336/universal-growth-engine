"""
Policy Evaluator

Given a context snapshot (behavioral profile + predictions),
evaluates all active policies and returns ranked candidate decisions.

The evaluator:
1. Filters policies by trigger event and targeting
2. Evaluates conditions for each policy
3. Applies fatigue and constraint checks
4. Ranks surviving candidates by priority
5. Returns the top-ranked decision

Fatigue management:
- Cooldown: minimum hours between two executions of the same policy for the same identity
- Communication cap: max N messages per identity per day across all channels
- Channel block: respects unsubscribed channels
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

from core.behavior.schema import BehavioralProfile
from core.prediction.schema import PredictionSet, PredictionType

from .schema import Decision, DecisionContext, DecisionStatus, ActionType
from .policy import Policy, PolicyRegistry

logger = logging.getLogger(__name__)

# Max outbound communications per identity per 24h window
DEFAULT_DAILY_COMM_CAP = 3

# Action types that count as outbound communications
COMM_ACTION_TYPES = {
    ActionType.SEND_EMAIL,
    ActionType.SEND_PUSH,
    ActionType.SEND_SMS,
    ActionType.SEND_WHATSAPP,
    ActionType.SEND_IN_APP,
}


class EvaluationResult:
    """Result from evaluating a single policy."""

    def __init__(
        self,
        policy: Policy,
        matched: bool,
        suppressed: bool = False,
        suppression_reason: str = "",
    ):
        self.policy = policy
        self.matched = matched
        self.suppressed = suppressed
        self.suppression_reason = suppression_reason


class PolicyEvaluator:
    """
    Evaluates all active policies against an identity context
    and returns ranked candidate decisions.

    Usage:
        evaluator = PolicyEvaluator(registry)
        decisions = evaluator.evaluate(
            profile=profile,
            prediction_set=prediction_set,
            trigger_event_type="PAYMENT_COMPLETED",
            decision_history=past_decisions,
        )
    """

    def __init__(
        self,
        registry: PolicyRegistry,
        daily_comm_cap: int = DEFAULT_DAILY_COMM_CAP,
    ):
        self._registry = registry
        self._daily_comm_cap = daily_comm_cap

    def evaluate(
        self,
        profile: BehavioralProfile,
        prediction_set: PredictionSet,
        trigger_event_type: Optional[str] = None,
        decision_history: Optional[List[Decision]] = None,
        trigger_event_id: Optional[str] = None,
    ) -> List[Decision]:
        """
        Evaluate all active policies and return ranked candidate decisions.
        Returns decisions sorted by priority descending.
        """
        history = decision_history or []
        context = self._build_context(profile, prediction_set, trigger_event_type)

        policies = self._registry.get_active(
            application_id=profile.application_id,
            trigger_event=trigger_event_type,
        )

        candidates: List[Tuple[int, Decision]] = []
        evaluated_policy_names = []
        suppressed_actions = []

        for policy in policies:
            evaluated_policy_names.append(policy.name)

            # Targeting check
            if not policy.matches_target(context):
                logger.debug(f"Policy '{policy.name}' — targeting mismatch, skipping")
                continue

            # Condition check
            if not policy.evaluate_conditions(context):
                logger.debug(f"Policy '{policy.name}' — conditions not met, skipping")
                continue

            # Fatigue / constraint check
            suppressed, reason = self._check_suppression(
                policy=policy,
                profile=profile,
                history=history,
                context=context,
            )
            if suppressed:
                suppressed_actions.append(policy.action.action_type.value)
                logger.debug(
                    f"Policy '{policy.name}' suppressed — {reason}"
                )
                continue

            # Build decision
            decision = self._build_decision(
                policy=policy,
                profile=profile,
                context=context,
                evaluated_policy_names=evaluated_policy_names,
                suppressed_actions=suppressed_actions,
                trigger_event_type=trigger_event_type,
                trigger_event_id=trigger_event_id,
            )
            candidates.append((policy.action.priority, decision))
            logger.debug(
                f"Policy '{policy.name}' matched | "
                f"action={policy.action.action_type.value} "
                f"priority={policy.action.priority}"
            )

        # Sort by priority descending
        candidates.sort(key=lambda x: x[0], reverse=True)
        decisions = [d for _, d in candidates]

        logger.info(
            f"Evaluation complete | identity={profile.identity_id} "
            f"app={profile.application_id} "
            f"policies_evaluated={len(policies)} "
            f"decisions={len(decisions)} "
            f"trigger={trigger_event_type}"
        )

        return decisions

    def best_decision(
        self,
        profile: BehavioralProfile,
        prediction_set: PredictionSet,
        trigger_event_type: Optional[str] = None,
        decision_history: Optional[List[Decision]] = None,
        trigger_event_id: Optional[str] = None,
    ) -> Optional[Decision]:
        """Return only the highest-priority decision, or None."""
        decisions = self.evaluate(
            profile=profile,
            prediction_set=prediction_set,
            trigger_event_type=trigger_event_type,
            decision_history=decision_history,
            trigger_event_id=trigger_event_id,
        )
        return decisions[0] if decisions else None

    # ------------------------------------------------------------------
    # Context builder
    # ------------------------------------------------------------------

    def _build_context(
        self,
        profile: BehavioralProfile,
        prediction_set: PredictionSet,
        trigger_event_type: Optional[str],
    ) -> Dict:
        ctx = {}

        # Behavioral signals
        ctx["engagement_tier"] = profile.engagement.tier
        ctx["rfm_segment"] = profile.rfm.segment
        ctx["days_inactive"] = profile.churn.days_inactive
        ctx["churn_risk_level"] = profile.churn.risk_level
        ctx["total_sessions"] = profile.engagement.total_sessions
        ctx["total_conversions"] = profile.rfm.total_conversions
        ctx["unsubscribed_channels"] = profile.communication.unsubscribed_channels

        # Prediction scores
        for ptype in PredictionType:
            pred = prediction_set.get(ptype)
            ctx[f"{ptype.value}_score"] = pred.score if pred else None

        # Trigger
        ctx["trigger_event"] = trigger_event_type

        return ctx

    # ------------------------------------------------------------------
    # Suppression checks
    # ------------------------------------------------------------------

    def _check_suppression(
        self,
        policy: Policy,
        profile: BehavioralProfile,
        history: List[Decision],
        context: Dict,
    ) -> Tuple[bool, str]:
        """Returns (suppressed: bool, reason: str)."""

        now = datetime.now(timezone.utc)

        # 1. Cooldown check
        if policy.cooldown_hours > 0:
            cutoff = now - timedelta(hours=policy.cooldown_hours)
            recent = [
                d for d in history
                if d.context.policy_id == policy.id
                and d.created_at >= cutoff
                and d.status not in (DecisionStatus.SUPPRESSED, DecisionStatus.EXPIRED)
            ]
            if recent:
                return True, f"cooldown active (last executed within {policy.cooldown_hours}h)"

        # 2. Max executions check
        if policy.max_executions_per_identity > 0:
            total = [
                d for d in history
                if d.context.policy_id == policy.id
                and d.status == DecisionStatus.EXECUTED
            ]
            if len(total) >= policy.max_executions_per_identity:
                return True, f"max executions reached ({policy.max_executions_per_identity})"

        # 3. Channel block check
        channel = policy.action.channel
        if channel and channel in context.get("unsubscribed_channels", []):
            return True, f"identity unsubscribed from channel '{channel}'"

        # 4. Daily communication cap
        if policy.action.action_type in COMM_ACTION_TYPES:
            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            comms_today = [
                d for d in history
                if d.action_type in COMM_ACTION_TYPES
                and d.created_at >= day_start
                and d.status not in (DecisionStatus.SUPPRESSED, DecisionStatus.EXPIRED)
            ]
            if len(comms_today) >= self._daily_comm_cap:
                return True, f"daily communication cap reached ({self._daily_comm_cap})"

        return False, ""

    # ------------------------------------------------------------------
    # Decision builder
    # ------------------------------------------------------------------

    def _build_decision(
        self,
        policy: Policy,
        profile: BehavioralProfile,
        context: Dict,
        evaluated_policy_names: List[str],
        suppressed_actions: List[str],
        trigger_event_type: Optional[str],
        trigger_event_id: Optional[str],
    ) -> Decision:
        now = datetime.now(timezone.utc)

        decision_context = DecisionContext(
            churn_score=context.get("churn_score"),
            conversion_score=context.get("conversion_score"),
            ltv_score=context.get("ltv_score"),
            upsell_score=context.get("upsell_score"),
            referral_score=context.get("referral_score"),
            fraud_score=context.get("fraud_score"),
            engagement_tier=context.get("engagement_tier"),
            rfm_segment=context.get("rfm_segment"),
            days_inactive=context.get("days_inactive"),
            churn_risk_level=context.get("churn_risk_level"),
            policy_id=policy.id,
            policy_name=policy.name,
            evaluated_policies=list(evaluated_policy_names),
            suppressed_actions=list(suppressed_actions),
            trigger_event_type=trigger_event_type,
            trigger_event_id=trigger_event_id,
        )

        execute_after = None
        if policy.action.delay_hours > 0:
            execute_after = now + timedelta(hours=policy.action.delay_hours)

        valid_until = now + timedelta(hours=policy.action.valid_hours)

        return Decision(
            identity_id=profile.identity_id,
            application_id=profile.application_id,
            action_type=policy.action.action_type,
            priority=policy.action.priority,
            payload=dict(policy.action.payload_template),
            channel=policy.action.channel,
            execute_after=execute_after,
            valid_until=valid_until,
            context=decision_context,
        )
