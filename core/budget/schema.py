"""
Budget Allocation Schema

Pydantic models for the self-optimizing budget allocator.

Tracks per-channel spend, conversions, CAC, and ROI.
Supports automatic reallocation based on channel performance.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Channel(str, Enum):
    EMAIL = "email"
    PUSH = "push"
    SMS = "sms"
    WHATSAPP = "whatsapp"
    META_ADS = "meta_ads"
    GOOGLE_ADS = "google_ads"
    TIKTOK_ADS = "tiktok_ads"
    LINKEDIN_ADS = "linkedin_ads"
    REFERRAL = "referral"
    ORGANIC = "organic"


class ChannelBudget(BaseModel):
    channel: str
    allocated_budget: float = 0.0
    spent: float = 0.0
    status: str = "active"
    auto_pause_threshold: float = 0.0
    min_budget: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def remaining(self) -> float:
        return max(self.allocated_budget - self.spent, 0.0)


class ChannelPerformance(BaseModel):
    channel: str
    total_actions: int = 0
    successful_actions: int = 0
    conversions: int = 0
    total_spend: float = 0.0
    conversion_rate: float = 0.0
    cac: Optional[float] = None
    roi: float = 0.0
    last_conversion_at: Optional[datetime] = None
    first_action_at: Optional[datetime] = None
    performance_trend: str = "stable"
    recent_conversion_rates: List[float] = Field(default_factory=list)


class BudgetPlan(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    platform_id: str
    total_budget: float
    period: str = "monthly"
    channel_budgets: Dict[str, ChannelBudget] = Field(default_factory=dict)
    auto_optimize: bool = True
    optimization_frequency: str = "daily"
    reallocation_strategy: str = "proportional"
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    status: str = "active"


class ReallocationChange(BaseModel):
    channel: str
    old_budget: float
    new_budget: float
    reason: str


class ReallocationEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    plan_id: str
    platform_id: str
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    reason: str = ""
    changes: List[ReallocationChange] = Field(default_factory=list)
    trigger: str = "auto"
