"""
Entity Schema

The universal entity model.

The engine never hardcodes Buyer, Seller, Trader, Product.
It manages generic entities. Applications define their own types.

Every object that matters in any application is an Entity:
- Users, Buyers, Sellers, Traders
- Products, Services, Listings, Assets
- Organizations, Teams
- Orders, Portfolios, Campaigns
- Anything the application registers
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class EntityStatus(str, Enum):
    """Lifecycle status of an entity."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING = "pending"
    SUSPENDED = "suspended"
    DELETED = "deleted"
    ARCHIVED = "archived"


class EntityType(str, Enum):
    """
    Built-in entity types understood by the engine.
    Applications register additional domain-specific types
    via the EntityRegistry.
    """
    # People
    USER = "User"
    ORGANIZATION = "Organization"
    TEAM = "Team"

    # Commerce
    PRODUCT = "Product"
    SERVICE = "Service"
    LISTING = "Listing"
    ORDER = "Order"
    SUBSCRIPTION = "Subscription"

    # Finance
    ACCOUNT = "Account"
    PORTFOLIO = "Portfolio"
    ASSET = "Asset"
    TRANSACTION = "Transaction"

    # Growth
    CAMPAIGN = "Campaign"
    REFERRAL = "Referral"
    EXPERIMENT = "Experiment"

    # Platform
    MARKETPLACE = "Marketplace"
    DOCUMENT = "Document"
    REVIEW = "Review"
    DISPUTE = "Dispute"

    # Custom — applications define the actual type via type_name
    CUSTOM = "Custom"


class RelationshipType(str, Enum):
    """
    Built-in relationship types between entities.
    Applications may register additional types.
    """
    OWNS = "owns"                   # User owns Portfolio
    BELONGS_TO = "belongs_to"       # Product belongs_to Organization
    CREATED = "created"             # User created Listing
    PURCHASED = "purchased"         # User purchased Product
    SELLS = "sells"                 # Seller sells Service
    FOLLOWS = "follows"             # User follows Organization
    MANAGES = "manages"             # User manages Team
    INVITED = "invited"             # User invited User
    REVIEWED = "reviewed"           # User reviewed Service
    DISPUTED = "disputed"           # User disputed Order
    PARTICIPATED_IN = "participated_in"
    REFERRED = "referred"
    SUBSCRIBED_TO = "subscribed_to"
    CUSTOM = "custom"


class AttributeHistory(BaseModel):
    """A single historical record of an attribute change."""
    key: str
    old_value: Optional[Any] = None
    new_value: Any
    changed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    changed_by: Optional[str] = None   # entity_id of the actor


class EntityRelationship(BaseModel):
    """
    A directed relationship between two entities.

    Example:
        source_id=user_001, type=OWNS, target_id=portfolio_001
        source_id=seller_001, type=SELLS, target_id=service_002
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_id: str
    source_type: str
    relationship_type: RelationshipType
    custom_relationship_type: Optional[str] = None
    target_id: str
    target_type: str
    application_id: str
    properties: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    valid_until: Optional[datetime] = None

    def is_active(self) -> bool:
        if self.valid_until is None:
            return True
        return datetime.now(timezone.utc) < self.valid_until

    def label(self) -> str:
        if self.relationship_type == RelationshipType.CUSTOM:
            return self.custom_relationship_type or "custom"
        return self.relationship_type.value


class Entity(BaseModel):
    """
    The universal entity.

    Every object in every application that the engine tracks
    is represented as an Entity.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    application_id: str
    type: EntityType = EntityType.CUSTOM
    type_name: str = Field(..., description="Actual type label e.g. 'Buyer', 'Trader', 'Listing'")

    # Lifecycle
    status: EntityStatus = EntityStatus.ACTIVE
    state: Optional[str] = Field(
        None,
        description="Current state in the entity's state machine (e.g. 'kyc_pending')"
    )
    state_history: List[Dict[str, Any]] = Field(default_factory=list)

    # Identity link
    identity_id: Optional[str] = Field(
        None,
        description="Linked UGIE identity ID (for person-type entities)"
    )

    # Attributes — domain-defined key-value store
    attributes: Dict[str, Any] = Field(default_factory=dict)
    attribute_history: List[AttributeHistory] = Field(default_factory=list)

    # Relationships (stored as IDs — full objects fetched from repository)
    relationship_ids: List[str] = Field(default_factory=list)

    # Scoring signals (computed by behavior/intelligence layers)
    scores: Dict[str, float] = Field(default_factory=dict)

    # Tags — free-form categorization
    tags: List[str] = Field(default_factory=list)

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_active_at: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Attribute management
    # ------------------------------------------------------------------

    def set_attribute(
        self,
        key: str,
        value: Any,
        changed_by: Optional[str] = None,
    ) -> "Entity":
        """Set an attribute, recording history."""
        old_value = self.attributes.get(key)
        if old_value != value:
            self.attribute_history.append(AttributeHistory(
                key=key,
                old_value=old_value,
                new_value=value,
                changed_by=changed_by,
            ))
            self.attributes[key] = value
            self.updated_at = datetime.now(timezone.utc)
        return self

    def get_attribute(self, key: str, default: Any = None) -> Any:
        return self.attributes.get(key, default)

    def set_attributes(self, attrs: Dict[str, Any], changed_by: Optional[str] = None) -> "Entity":
        for key, value in attrs.items():
            self.set_attribute(key, value, changed_by)
        return self

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def transition_state(self, new_state: str, triggered_by: Optional[str] = None) -> "Entity":
        """Transition to a new state, recording history."""
        old_state = self.state
        self.state_history.append({
            "from": old_state,
            "to": new_state,
            "at": datetime.now(timezone.utc).isoformat(),
            "triggered_by": triggered_by,
        })
        self.state = new_state
        self.updated_at = datetime.now(timezone.utc)
        return self

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def set_score(self, key: str, value: float) -> "Entity":
        """Set a computed score (e.g. churn_probability, trust_score)."""
        self.scores[key] = value
        self.updated_at = datetime.now(timezone.utc)
        return self

    def get_score(self, key: str, default: float = 0.0) -> float:
        return self.scores.get(key, default)

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------

    def add_tag(self, tag: str) -> "Entity":
        if tag not in self.tags:
            self.tags.append(tag)
        return self

    def remove_tag(self, tag: str) -> "Entity":
        self.tags = [t for t in self.tags if t != tag]
        return self

    def has_tag(self, tag: str) -> bool:
        return tag in self.tags

    # ------------------------------------------------------------------
    # Activity
    # ------------------------------------------------------------------

    def touch(self) -> "Entity":
        now = datetime.now(timezone.utc)
        self.last_active_at = now
        self.updated_at = now
        return self

    def is_active(self) -> bool:
        return self.status == EntityStatus.ACTIVE
