"""
Analytics Schema

Pydantic models for analytics dashboard responses.
All models are read-only aggregations computed from existing subsystems.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class FunnelMetrics(BaseModel):
    total_identities: int = 0
    registered: int = 0
    activated: int = 0
    converted: int = 0
    retained: int = 0
    registration_to_activation_rate: float = 0.0
    activation_to_conversion_rate: float = 0.0
    conversion_to_retention_rate: float = 0.0
    overall_conversion_rate: float = 0.0


class EngagementBreakdown(BaseModel):
    cold: int = 0
    warming: int = 0
    active: int = 0
    power: int = 0
    total: int = 0


class RFMBreakdown(BaseModel):
    new: int = 0
    promising: int = 0
    loyal: int = 0
    champions: int = 0
    at_risk: int = 0
    hibernating: int = 0
    lost: int = 0
    total: int = 0


class ChurnBreakdown(BaseModel):
    low: int = 0
    medium: int = 0
    high: int = 0
    critical: int = 0
    total: int = 0


class PredictionSummary(BaseModel):
    prediction_type: str
    total_predictions: int = 0
    avg_score: float = 0.0
    high_risk_count: int = 0
    medium_risk_count: int = 0
    low_risk_count: int = 0


class ExperimentSummary(BaseModel):
    total_experiments: int = 0
    running: int = 0
    completed: int = 0
    draft: int = 0
    paused: int = 0
    experiments: List[Dict[str, Any]] = Field(default_factory=list)


class ReferralSummary(BaseModel):
    total_programs: int = 0
    total_codes: int = 0
    total_referrals: int = 0
    referrals_by_status: Dict[str, int] = Field(default_factory=dict)


class AudienceSummary(BaseModel):
    total_audiences: int = 0
    by_status: Dict[str, int] = Field(default_factory=dict)


class PlatformDashboard(BaseModel):
    platform_id: str
    platform_name: str = ""
    computed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    funnel: FunnelMetrics = Field(default_factory=FunnelMetrics)
    engagement: EngagementBreakdown = Field(default_factory=EngagementBreakdown)
    rfm: RFMBreakdown = Field(default_factory=RFMBreakdown)
    churn: ChurnBreakdown = Field(default_factory=ChurnBreakdown)
    predictions: List[PredictionSummary] = Field(default_factory=list)
    experiments: ExperimentSummary = Field(default_factory=ExperimentSummary)
    referrals: ReferralSummary = Field(default_factory=ReferralSummary)
    audiences: AudienceSummary = Field(default_factory=AudienceSummary)
    identity_stats: Dict[str, Any] = Field(default_factory=dict)
    cross_platform: Dict[str, Any] = Field(default_factory=dict)
