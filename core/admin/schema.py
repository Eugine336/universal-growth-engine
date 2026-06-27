"""
Admin Schema

Models for system administration and platform management.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PlatformConfigUpdate(BaseModel):
    name: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class SystemHealth(BaseModel):
    total_platforms: int = 0
    total_identities: int = 0
    total_profiles: int = 0
    total_experiments: int = 0
    total_audiences: int = 0
    total_referral_programs: int = 0
    components: Dict[str, str] = Field(default_factory=dict)
    computed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
