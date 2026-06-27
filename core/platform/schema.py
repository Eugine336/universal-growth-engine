"""
Platform Schema

Defines the Platform model — a tenant in the multi-tenant UGIE system.
Each platform has its own API key, quotas, and domain configuration.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class PlatformStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"


class PlatformQuotas(BaseModel):
    max_events_per_hour: int = 10000
    max_entities: int = 100000
    max_decisions_per_hour: int = 5000


def generate_api_key() -> str:
    return f"ugie_{uuid.uuid4().hex}"


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


class Platform(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    slug: str
    api_key_hash: str = ""
    api_key_prefix: str = ""
    status: PlatformStatus = PlatformStatus.ACTIVE
    owner_email: str
    config_yaml: Optional[str] = None
    quotas: PlatformQuotas = Field(default_factory=PlatformQuotas)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def set_api_key(self, raw_key: str) -> None:
        self.api_key_hash = hash_api_key(raw_key)
        self.api_key_prefix = raw_key[:8]

    def verify_api_key(self, raw_key: str) -> bool:
        return hash_api_key(raw_key) == self.api_key_hash

    def is_active(self) -> bool:
        return self.status == PlatformStatus.ACTIVE
