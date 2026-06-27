"""
Policy

A Policy is a rule that says:
  IF these conditions are true
  THEN take this action
  WITH these constraints

Policies are registered per application.
The engine evaluates all active policies against every identity
and selects the highest-priority matching action.

Policies are:
- Condition-based (score thresholds, event triggers, state checks)
- Prioritized (higher priority wins)
- Constrained (cooldown, max executions, channel limits)
- Targeted (entity type, rfm segment, engagement tier filters)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Dict, List, Optional

from .schema import ActionType


# ---------------------------------------------------------------------------
# Condition
# ---------------------------------------------------------------------------

@dataclass
class PolicyCondition:
    """
    A single evaluatable condition.

    Example:
        PolicyCondition(
            field="churn_score",
            operator="gte",
            value=0.7,
        )
    """
    field: str
    operator: str       # eq | neq | gt | gte | lt | lte | in | not_in | exists
    value: Any
    label: str = ""

    def evaluate(self, context: Dict[str, Any]) -> bool:
        actual = context.get(self.field)

        if self.operator == "exists":
            return actual is not None
        if actual is None:
            return False

        ops = {
            "eq":     lambda a, v: a == v,
            "neq":    lambda a, v: a != v,
            "gt":     lambda a, v: a > v,
            "gte":    lambda a, v: a >= v,
            "lt":     lambda a, v: a < v,
            "lte":    lambda a, v: a <= v,
            "in":     lambda a, v: a in v,
            "not_in": lambda a, v: a not in v,
        }
        fn = ops.get(self.operator)
        if not fn:
            raise ValueError(f"Unknown operator: {self.operator}")
        try:
            return fn(actual, self.value)
        except TypeError:
            return False


# ---------------------------------------------------------------------------
# Policy Action
# ---------------------------------------------------------------------------

@dataclass
class PolicyAction:
    """
    What the policy wants to do when its conditions are met.
    """
    action_type: ActionType
    channel: Optional[str] = None
    payload_template: Dict[str, Any] = field(default_factory=dict)
    priority: int = 50          # 0 = lowest, 100 = highest
    delay_hours: float = 0.0    # Wait N hours before executing
    valid_hours: float = 24.0   # Decision expires after N hours


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

@dataclass
class Policy:
    """
    A complete policy rule.

    Conditions are ANDed by default.
    Set condition_logic="OR" to OR them.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    application_id: str = ""
    name: str = ""
    description: str = ""

    # Trigger
    trigger_events: List[str] = field(default_factory=list)  # empty = evaluate always
    conditions: List[PolicyCondition] = field(default_factory=list)
    condition_logic: str = "AND"    # AND | OR

    # Target filters (empty = all)
    target_entity_types: List[str] = field(default_factory=list)
    target_rfm_segments: List[str] = field(default_factory=list)
    target_engagement_tiers: List[str] = field(default_factory=list)

    # Action
    action: PolicyAction = field(default_factory=lambda: PolicyAction(ActionType.NO_ACTION))

    # Constraints
    cooldown_hours: float = 24.0        # Min hours between executions for same identity
    max_executions_per_identity: int = 0  # 0 = unlimited
    abort_if_events: List[str] = field(default_factory=list)  # Cancel if these fire first

    # Lifecycle
    enabled: bool = True
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None

    def is_active(self) -> bool:
        if not self.enabled:
            return False
        now = datetime.now(timezone.utc)
        if self.starts_at and now < self.starts_at:
            return False
        if self.ends_at and now > self.ends_at:
            return False
        return True

    def matches_trigger(self, event_type: Optional[str]) -> bool:
        """True if this policy should be evaluated for this event type."""
        if not self.trigger_events:
            return True     # No trigger filter — always evaluate
        return event_type in self.trigger_events

    def matches_target(self, context: Dict[str, Any]) -> bool:
        """True if the identity matches the targeting filters."""
        if self.target_entity_types:
            if context.get("entity_type") not in self.target_entity_types:
                return False
        if self.target_rfm_segments:
            if context.get("rfm_segment") not in self.target_rfm_segments:
                return False
        if self.target_engagement_tiers:
            if context.get("engagement_tier") not in self.target_engagement_tiers:
                return False
        return True

    def evaluate_conditions(self, context: Dict[str, Any]) -> bool:
        """Evaluate all conditions against the context."""
        if not self.conditions:
            return True
        results = [c.evaluate(context) for c in self.conditions]
        if self.condition_logic == "OR":
            return any(results)
        return all(results)


# ---------------------------------------------------------------------------
# Policy Registry
# ---------------------------------------------------------------------------

class PolicyRegistry:
    """
    Maintains all registered policies per application.

    Usage:
        registry = PolicyRegistry()
        registry.register(policy)
        policies = registry.get_active("ucmc")
    """

    def __init__(self):
        self._policies: Dict[str, Policy] = {}
        self._seed_global_policies()

    def register(self, policy: Policy) -> None:
        self._policies[policy.id] = policy

    def get(self, policy_id: str) -> Optional[Policy]:
        return self._policies.get(policy_id)

    def get_active(
        self,
        application_id: str,
        trigger_event: Optional[str] = None,
    ) -> List[Policy]:
        """Return all active policies for an application that match the trigger."""
        return [
            p for p in self._policies.values()
            if (p.application_id == application_id or p.application_id == "*")
            and p.is_active()
            and p.matches_trigger(trigger_event)
        ]

    def disable(self, policy_id: str) -> None:
        policy = self._policies.get(policy_id)
        if policy:
            policy.enabled = False

    def enable(self, policy_id: str) -> None:
        policy = self._policies.get(policy_id)
        if policy:
            policy.enabled = True

    def list_for_application(self, application_id: str) -> List[Policy]:
        return [
            p for p in self._policies.values()
            if p.application_id in (application_id, "*")
        ]

    def count(self, application_id: Optional[str] = None) -> int:
        if not application_id:
            return len(self._policies)
        return len(self.list_for_application(application_id))

    # ------------------------------------------------------------------
    # Global built-in policies (apply to all applications)
    # ------------------------------------------------------------------

    def _seed_global_policies(self) -> None:
        """
        Seed universal policies that apply across all applications.
        Applications can override these with higher-priority policies.
        """
        from datetime import timezone

        # Churn re-engagement
        self.register(Policy(
            id="global_churn_reengagement",
            application_id="*",
            name="Churn Re-engagement",
            description="Trigger re-engagement when churn risk is high",
            conditions=[
                PolicyCondition(field="churn_score", operator="gte", value=0.6),
                PolicyCondition(field="days_inactive", operator="gte", value=14.0),
            ],
            action=PolicyAction(
                action_type=ActionType.TRIGGER_REENGAGEMENT,
                priority=70,
                payload_template={"template": "reengagement_default"},
                valid_hours=48.0,
            ),
            cooldown_hours=72.0,
            abort_if_events=["SESSION_STARTED", "PAYMENT_COMPLETED"],
        ))

        # High fraud risk — flag for review
        self.register(Policy(
            id="global_fraud_flag",
            application_id="*",
            name="Fraud Risk Flag",
            description="Flag identities with high fraud probability for review",
            conditions=[
                PolicyCondition(field="fraud_score", operator="gte", value=0.65),
            ],
            action=PolicyAction(
                action_type=ActionType.FLAG_FOR_REVIEW,
                priority=95,
                payload_template={"reason": "high_fraud_probability"},
                valid_hours=24.0,
            ),
            cooldown_hours=48.0,
        ))

        # Request review after conversion
        self.register(Policy(
            id="global_request_review",
            application_id="*",
            name="Request Review Post-Conversion",
            description="Ask for a review after a successful conversion",
            trigger_events=["PAYMENT_COMPLETED", "ORDER_COMPLETED"],
            conditions=[
                PolicyCondition(field="fraud_score", operator="lt", value=0.3),
            ],
            action=PolicyAction(
                action_type=ActionType.REQUEST_REVIEW,
                priority=40,
                payload_template={"template": "review_request_default"},
                delay_hours=24.0,
                valid_hours=72.0,
            ),
            cooldown_hours=168.0,   # Once per week
        ))

        # Upsell champions
        self.register(Policy(
            id="global_upsell_champions",
            application_id="*",
            name="Upsell Champions",
            description="Show upsell offer to champion-segment users",
            target_rfm_segments=["champions", "loyal"],
            conditions=[
                PolicyCondition(field="upsell_score", operator="gte", value=0.5),
                PolicyCondition(field="churn_score", operator="lt", value=0.3),
            ],
            action=PolicyAction(
                action_type=ActionType.SHOW_UPSELL,
                priority=60,
                payload_template={"template": "upsell_champion"},
                valid_hours=48.0,
            ),
            cooldown_hours=168.0,
        ))

        # Referral ask for power users
        self.register(Policy(
            id="global_referral_ask",
            application_id="*",
            name="Referral Ask — Power Users",
            description="Ask power users to refer friends",
            target_engagement_tiers=["power"],
            conditions=[
                PolicyCondition(field="referral_score", operator="gte", value=0.4),
            ],
            action=PolicyAction(
                action_type=ActionType.SEND_EMAIL,
                channel="email",
                priority=45,
                payload_template={"template": "referral_ask"},
                valid_hours=72.0,
            ),
            cooldown_hours=336.0,   # Once per 2 weeks
        ))
