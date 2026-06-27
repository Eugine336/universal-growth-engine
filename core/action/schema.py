"""
Action Schema

An Action is a Decision that has been committed to execution.

When the decision engine produces a Decision, the orchestrator
converts it into an Action and hands it to the right connector.

Actions are:
- Immutable once dispatched (new action for retries)
- Tracked (status, attempts, results)
- Auditable (full payload and result stored)
- Feedback-capable (results feed back into the event bus)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ActionStatus(str, Enum):
    QUEUED = "queued"
    DISPATCHED = "dispatched"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRYING = "retrying"
    EXHAUSTED = "exhausted"     # Max retries reached
    CANCELLED = "cancelled"


class ActionResult(BaseModel):
    """Result returned by a connector after executing an action."""
    success: bool
    connector_id: str
    connector_ref: Optional[str] = None     # External reference (e.g. email message_id)
    response: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    executed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: Optional[float] = None


class ConnectorManifest(BaseModel):
    """
    Metadata about a registered connector.
    Declares which ActionTypes it handles and its capabilities.
    """
    id: str
    name: str
    description: str = ""
    supported_action_types: List[str] = Field(default_factory=list)
    requires_channel: bool = False
    supports_scheduling: bool = False
    supports_batching: bool = False
    enabled: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Action(BaseModel):
    """
    A committed, executable unit of work handed to a connector.

    Derived from a Decision — includes everything the connector
    needs to do its job.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    decision_id: str
    identity_id: str
    application_id: str

    # What to do
    action_type: str
    connector_id: Optional[str] = None
    channel: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)

    # Scheduling
    scheduled_at: Optional[datetime] = None
    execute_after: Optional[datetime] = None
    valid_until: Optional[datetime] = None

    # Execution tracking
    status: ActionStatus = ActionStatus.QUEUED
    attempts: int = 0
    max_attempts: int = 3
    results: List[ActionResult] = Field(default_factory=list)
    last_error: Optional[str] = None

    # Feedback tracking (filled after downstream measurement)
    feedback: Dict[str, Any] = Field(default_factory=dict)

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    dispatched_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Context passthrough for feedback loop
    context: Dict[str, Any] = Field(default_factory=dict)

    def is_executable(self) -> bool:
        if self.status not in (ActionStatus.QUEUED, ActionStatus.RETRYING):
            return False
        if self.attempts >= self.max_attempts:
            return False
        if self.valid_until and datetime.now(timezone.utc) > self.valid_until:
            return False
        if self.execute_after and datetime.now(timezone.utc) < self.execute_after:
            return False
        return True

    def can_retry(self) -> bool:
        return self.attempts < self.max_attempts and self.status not in (ActionStatus.CANCELLED, ActionStatus.EXHAUSTED, ActionStatus.SUCCEEDED)

    def record_attempt(self, result: ActionResult) -> "Action":
        self.attempts += 1
        self.results.append(result)
        self.updated_at = datetime.now(timezone.utc)

        if result.success:
            self.status = ActionStatus.SUCCEEDED
            self.completed_at = datetime.now(timezone.utc)
            self.last_error = None
        else:
            self.last_error = result.error
            if self.attempts >= self.max_attempts:
                self.status = ActionStatus.EXHAUSTED
                self.completed_at = datetime.now(timezone.utc)
            else:
                self.status = ActionStatus.RETRYING

        return self

    def latest_result(self) -> Optional[ActionResult]:
        return self.results[-1] if self.results else None
