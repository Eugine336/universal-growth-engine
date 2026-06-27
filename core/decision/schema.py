"""
Decision Schema

A Decision is the engine's output for a single identity at a point in time.

It says:
  Given everything I know about this identity —
  their behavior, predictions, and the active policies —
  the best next action is X.

Decisions are:
- Typed (what action category)
- Prioritized (higher priority wins when multiple actions compete)
- Constrained (respects fatigue, blackout, channel blocks)
- Auditable (full context recorded for learning loop)
- Time-bounded (expire if not executed within window)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ActionType(str, Enum):
    """The type of action the engine wants to execute."""
    # Communication
    SEND_EMAIL = "SEND_EMAIL"
    SEND_PUSH = "SEND_PUSH"
    SEND_SMS = "SEND_SMS"
    SEND_WHATSAPP = "SEND_WHATSAPP"
    SEND_IN_APP = "SEND_IN_APP"

    # Advertising
    RUN_META_CAMPAIGN = "RUN_META_CAMPAIGN"
    RUN_GOOGLE_CAMPAIGN = "RUN_GOOGLE_CAMPAIGN"
    RUN_TIKTOK_CAMPAIGN = "RUN_TIKTOK_CAMPAIGN"
    RUN_LINKEDIN_CAMPAIGN = "RUN_LINKEDIN_CAMPAIGN"
    SUPPRESS_AD = "SUPPRESS_AD"

    # Product
    SHOW_RECOMMENDATION = "SHOW_RECOMMENDATION"
    SHOW_DISCOUNT = "SHOW_DISCOUNT"
    SHOW_UPSELL = "SHOW_UPSELL"
    SHOW_ONBOARDING = "SHOW_ONBOARDING"
    UNLOCK_FEATURE = "UNLOCK_FEATURE"

    # Workflow
    START_WORKFLOW = "START_WORKFLOW"
    ESCALATE_SUPPORT = "ESCALATE_SUPPORT"
    REQUEST_REVIEW = "REQUEST_REVIEW"
    FLAG_FOR_REVIEW = "FLAG_FOR_REVIEW"
    TRIGGER_RETENTION = "TRIGGER_RETENTION"
    TRIGGER_REENGAGEMENT = "TRIGGER_REENGAGEMENT"

    # Commerce
    CREATE_DISCOUNT = "CREATE_DISCOUNT"
    OFFER_INCENTIVE = "OFFER_INCENTIVE"

    # Internal
    NO_ACTION = "NO_ACTION"
    DELAY = "DELAY"


class DecisionStatus(str, Enum):
    PENDING = "pending"         # Waiting to be executed
    EXECUTING = "executing"     # Being executed by a connector
    EXECUTED = "executed"       # Successfully executed
    SKIPPED = "skipped"         # Conditions changed before execution
    FAILED = "failed"           # Execution failed
    EXPIRED = "expired"         # Not executed within validity window
    SUPPRESSED = "suppressed"   # Suppressed by fatigue or constraint


class DecisionContext(BaseModel):
    """
    Full context snapshot at the moment of decision.
    Stored for auditability and learning.
    """
    # Prediction scores at decision time
    churn_score: Optional[float] = None
    conversion_score: Optional[float] = None
    ltv_score: Optional[float] = None
    upsell_score: Optional[float] = None
    referral_score: Optional[float] = None
    fraud_score: Optional[float] = None

    # Behavioral signals
    engagement_tier: Optional[str] = None
    rfm_segment: Optional[str] = None
    days_inactive: Optional[float] = None
    churn_risk_level: Optional[str] = None

    # Policy that triggered this decision
    policy_id: Optional[str] = None
    policy_name: Optional[str] = None

    # Competing actions that were considered
    evaluated_policies: List[str] = Field(default_factory=list)
    suppressed_actions: List[str] = Field(default_factory=list)

    # Extra context from the triggering event
    trigger_event_type: Optional[str] = None
    trigger_event_id: Optional[str] = None


class DecisionOutcome(BaseModel):
    """Records the result of an executed decision."""
    executed_at: Optional[datetime] = None
    connector_id: Optional[str] = None
    connector_response: Optional[Dict[str, Any]] = None
    success: bool = False
    error: Optional[str] = None

    # Downstream measurement
    opened: bool = False
    clicked: bool = False
    converted: bool = False
    measured_at: Optional[datetime] = None


class Decision(BaseModel):
    """
    The engine's output — a single best-next-action for one identity.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    identity_id: str
    application_id: str
    entity_id: Optional[str] = None
    entity_type: Optional[str] = None

    # The action
    action_type: ActionType
    priority: int = Field(50, ge=0, le=100, description="0=lowest, 100=highest")

    # Action payload — connector-specific parameters
    payload: Dict[str, Any] = Field(default_factory=dict)

    # Execution constraints
    status: DecisionStatus = DecisionStatus.PENDING
    channel: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    execute_after: Optional[datetime] = None
    valid_until: Optional[datetime] = None

    # Context snapshot
    context: DecisionContext = Field(default_factory=DecisionContext)

    # Outcome (filled after execution)
    outcome: Optional[DecisionOutcome] = None

    # Experiment tracking
    experiment_id: Optional[str] = None
    variant_id: Optional[str] = None

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def is_expired(self) -> bool:
        if self.valid_until is None:
            return False
        return datetime.now(timezone.utc) > self.valid_until

    def is_executable(self) -> bool:
        if self.status != DecisionStatus.PENDING:
            return False
        if self.is_expired():
            return False
        if self.execute_after and datetime.now(timezone.utc) < self.execute_after:
            return False
        return True

    def mark_executed(self, outcome: DecisionOutcome) -> "Decision":
        self.status = DecisionStatus.EXECUTED
        self.outcome = outcome
        self.updated_at = datetime.now(timezone.utc)
        return self

    def mark_suppressed(self, reason: str) -> "Decision":
        self.status = DecisionStatus.SUPPRESSED
        self.payload["suppression_reason"] = reason
        self.updated_at = datetime.now(timezone.utc)
        return self

    def mark_expired(self) -> "Decision":
        self.status = DecisionStatus.EXPIRED
        self.updated_at = datetime.now(timezone.utc)
        return self
