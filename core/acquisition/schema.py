"""
Acquisition Schema

Data models for acquisition plans, audience specs, ad creatives,
and lookalike audience definitions.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Tuple


@dataclass
class AudienceSpec:
    name: str
    description: str
    age_min: int
    age_max: int
    interests: List[str]
    job_titles: List[str]
    locations: List[str]
    platforms: List[str]
    estimated_size: Optional[int] = None
    source: str = "category_knowledge"


@dataclass
class AdCreativeSpec:
    channel: str
    format: str
    headline: str
    body: str
    cta: str
    tone: str
    value_prop: str


@dataclass
class LookalikeSpec:
    source_audience: str
    seed_identity_ids: List[str]
    platform: str
    similarity_pct: int = 5


@dataclass
class ChannelPlan:
    channel: str
    priority: int
    recommended_budget_pct: float
    targeting: AudienceSpec
    creative: AdCreativeSpec
    expected_cac_range: Tuple[float, float]
    rationale: str


@dataclass
class AcquisitionPlan:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    platform_id: str = ""
    stage: str = "cold"
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    channel_plans: List[ChannelPlan] = field(default_factory=list)
    total_recommended_budget: Optional[float] = None
    estimated_cac: Optional[float] = None
    seed_audiences: List[AudienceSpec] = field(default_factory=list)
    creative_specs: List[AdCreativeSpec] = field(default_factory=list)
    lookalike_seeds: List[LookalikeSpec] = field(default_factory=list)
