"""
Experimentation Schema

Defines the data models for A/B testing at decision time.

An Experiment modifies a target policy by splitting traffic across variants.
Each variant can override policy fields (template, priority, payload, etc.).
Assignment is deterministic: hash(experiment_id + identity_id) → sticky variant.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ExperimentStatus(str, Enum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"


class ExperimentVariant(BaseModel):
    id: str
    name: str
    weight: float = 0.5
    policy_overrides: Dict[str, Any] = Field(default_factory=dict)


class Experiment(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    application_id: str
    name: str
    description: str = ""
    status: ExperimentStatus = ExperimentStatus.DRAFT

    target_policy_id: str
    variants: List[ExperimentVariant]

    target_rfm_segments: List[str] = Field(default_factory=list)
    target_engagement_tiers: List[str] = Field(default_factory=list)

    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    variant_counts: Dict[str, int] = Field(default_factory=dict)
    variant_conversions: Dict[str, int] = Field(default_factory=dict)


class ExperimentAssignment(BaseModel):
    experiment_id: str
    variant_id: str
    identity_id: str
    assigned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
