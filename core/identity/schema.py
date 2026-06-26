"""
Identity Schema

One person. One identity. Regardless of how many ways they interact.

A single human may arrive via:
- Google OAuth
- Email + password
- Mobile app (iOS / Android)
- Anonymous browser session
- API key
- Wallet address
- WhatsApp number
- Multiple devices

All of these resolve to a single Identity node in the graph.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class TouchpointType(str, Enum):
    """The channel or mechanism through which an identity was observed."""
    EMAIL = "email"
    PHONE = "phone"
    GOOGLE = "google"
    FACEBOOK = "facebook"
    APPLE = "apple"
    TWITTER = "twitter"
    LINKEDIN = "linkedin"
    GITHUB = "github"
    WALLET = "wallet"
    API_KEY = "api_key"
    DEVICE_ID = "device_id"
    COOKIE = "cookie"
    FINGERPRINT = "fingerprint"
    ANONYMOUS = "anonymous"
    CUSTOM = "custom"


class IdentityStatus(str, Enum):
    ACTIVE = "active"
    MERGED = "merged"         # This identity was merged into another
    SUSPENDED = "suspended"
    ANONYMOUS = "anonymous"   # Not yet identified


class IdentityTouchpoint(BaseModel):
    """
    A single observed identifier for an identity.

    Examples:
        - type=EMAIL, value="user@example.com"
        - type=GOOGLE, value="google_sub_id_abc123"
        - type=DEVICE_ID, value="device_xyz"
        - type=PHONE, value="+254700000000"
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: TouchpointType
    value: str = Field(..., description="The raw identifier value")
    application_id: Optional[str] = None
    verified: bool = False
    first_seen_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def key(self) -> str:
        """Unique lookup key for this touchpoint."""
        return f"{self.type.value}:{self.value.lower().strip()}"

    def touch(self) -> "IdentityTouchpoint":
        """Update last seen timestamp."""
        self.last_seen_at = datetime.now(timezone.utc)
        return self


class Identity(BaseModel):
    """
    A single persistent identity in the UGIE graph.

    Represents one real human (or system actor) regardless of
    how many touchpoints they have used.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: IdentityStatus = IdentityStatus.ANONYMOUS

    # All known touchpoints for this identity
    touchpoints: List[IdentityTouchpoint] = Field(default_factory=list)

    # Canonical identifiers (set once verified)
    canonical_email: Optional[str] = None
    canonical_phone: Optional[str] = None

    # Applications this identity has been seen in
    application_ids: List[str] = Field(default_factory=list)

    # Entity IDs this identity maps to (per application)
    # e.g. {"ucmc": "buyer_001", "trading": "trader_xyz"}
    entity_ids: Dict[str, str] = Field(default_factory=dict)

    # If this identity was merged into another
    merged_into: Optional[str] = None

    # Traits inferred or provided
    traits: Dict[str, Any] = Field(default_factory=dict)

    # Timestamps
    first_seen_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_seen_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Merge history
    merged_ids: List[str] = Field(default_factory=list)

    def touch(self, application_id: Optional[str] = None) -> "Identity":
        """Record activity."""
        now = datetime.now(timezone.utc)
        self.last_seen_at = now
        self.updated_at = now
        if application_id and application_id not in self.application_ids:
            self.application_ids.append(application_id)
        return self

    def add_touchpoint(self, touchpoint: IdentityTouchpoint) -> "Identity":
        """Add or update a touchpoint."""
        existing_keys = {tp.key() for tp in self.touchpoints}
        if touchpoint.key() not in existing_keys:
            self.touchpoints.append(touchpoint)
            # Set canonical identifiers
            if touchpoint.type == TouchpointType.EMAIL and not self.canonical_email:
                self.canonical_email = touchpoint.value.lower().strip()
            if touchpoint.type == TouchpointType.PHONE and not self.canonical_phone:
                self.canonical_phone = touchpoint.value.strip()
            # Promote status if identified
            if self.status == IdentityStatus.ANONYMOUS:
                if touchpoint.type not in {TouchpointType.ANONYMOUS,
                                           TouchpointType.COOKIE,
                                           TouchpointType.FINGERPRINT}:
                    self.status = IdentityStatus.ACTIVE
        else:
            # Touch the existing one
            for tp in self.touchpoints:
                if tp.key() == touchpoint.key():
                    tp.touch()
                    break
        self.updated_at = datetime.now(timezone.utc)
        return self

    def register_entity(self, application_id: str, entity_id: str) -> "Identity":
        """Map this identity to a domain entity in a specific application."""
        self.entity_ids[application_id] = entity_id
        if application_id not in self.application_ids:
            self.application_ids.append(application_id)
        self.updated_at = datetime.now(timezone.utc)
        return self

    def set_trait(self, key: str, value: Any) -> "Identity":
        self.traits[key] = value
        self.updated_at = datetime.now(timezone.utc)
        return self

    def touchpoint_keys(self) -> List[str]:
        return [tp.key() for tp in self.touchpoints]

    def is_anonymous(self) -> bool:
        return self.status == IdentityStatus.ANONYMOUS

    def is_merged(self) -> bool:
        return self.status == IdentityStatus.MERGED
