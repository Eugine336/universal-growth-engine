"""
Referral Schema

Defines the data models for the referral lifecycle:
- ReferralProgram: per-platform configuration for rewards and qualification
- ReferralCode: unique, human-readable codes generated for referrers
- Referral: a single referral conversion linking referrer to referee
- ReferralReward: tracks reward grants for both parties
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ReferralCodeStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


class RewardType(str, Enum):
    CREDIT = "credit"
    DISCOUNT_PERCENT = "discount_percent"
    FREE_PERIOD_DAYS = "free_period_days"
    CUSTOM = "custom"


class ReferralStatus(str, Enum):
    PENDING = "pending"
    QUALIFIED = "qualified"
    REWARDED = "rewarded"
    REJECTED = "rejected"


class ReferralReward(BaseModel):
    reward_type: RewardType
    reward_value: float
    reward_currency: Optional[str] = None
    status: str = "pending"
    granted_at: Optional[datetime] = None


class ReferralCode(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    platform_id: str
    referrer_identity_id: str
    referrer_entity_id: Optional[str] = None
    code: str
    status: ReferralCodeStatus = ReferralCodeStatus.ACTIVE
    reward_type: RewardType = RewardType.CREDIT
    reward_value: float = 0.0
    reward_currency: Optional[str] = None
    max_uses: int = 0
    current_uses: int = 0
    expires_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def is_usable(self) -> bool:
        if self.status != ReferralCodeStatus.ACTIVE:
            return False
        if self.expires_at and datetime.now(timezone.utc) > self.expires_at:
            return False
        if self.max_uses > 0 and self.current_uses >= self.max_uses:
            return False
        return True


class Referral(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    platform_id: str
    referral_code_id: str
    referrer_identity_id: str
    referee_identity_id: str
    referee_entity_id: Optional[str] = None
    status: ReferralStatus = ReferralStatus.PENDING
    qualification_event: Optional[str] = None
    referrer_reward: Optional[ReferralReward] = None
    referee_reward: Optional[ReferralReward] = None
    attributed_at: Optional[datetime] = None
    qualified_at: Optional[datetime] = None
    rewarded_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ReferralProgram(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    platform_id: str
    name: str
    status: str = "active"
    referrer_reward_type: RewardType = RewardType.CREDIT
    referrer_reward_value: float = 0.0
    referee_reward_type: RewardType = RewardType.CREDIT
    referee_reward_value: float = 0.0
    reward_currency: Optional[str] = None
    qualification_event: str = "USER_REGISTERED"
    double_sided: bool = True
    max_referrals_per_user: int = 0
    code_expiry_days: int = 90
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
