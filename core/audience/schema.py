"""
Audience Schema

An Audience is a named, reusable segment of behavioral profiles
defined by rules over profile fields.

Audiences can be exported to ad platforms as custom or lookalike audiences.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AudienceRule(BaseModel):
    """A single filter condition on a behavioral profile field."""
    field: str
    operator: str  # eq, neq, gt, gte, lt, lte, in, not_in, contains, exists
    value: Any = None


class AudienceRuleGroup(BaseModel):
    """AND/OR group of rules."""
    operator: str = "AND"  # AND | OR
    rules: List[AudienceRule] = Field(default_factory=list)


class AudienceDefinition(BaseModel):
    """Complete audience definition — groups are AND'd together."""
    name: str
    description: str = ""
    groups: List[AudienceRuleGroup] = Field(default_factory=list)


class Audience(BaseModel):
    """A stored, evaluable audience."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    platform_id: str
    definition: AudienceDefinition
    member_count: int = 0
    last_evaluated_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "draft"  # draft | active | archived
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ExportDestination(str, Enum):
    META = "meta"
    GOOGLE = "google"
    TIKTOK = "tiktok"
    LINKEDIN = "linkedin"


class ExportJob(BaseModel):
    """Tracks audience export to an ad platform."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    audience_id: str
    platform_id: str
    destination: ExportDestination
    status: str = "pending"  # pending | processing | completed | failed
    records_exported: int = 0
    external_audience_id: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    config: Dict[str, Any] = Field(default_factory=dict)
