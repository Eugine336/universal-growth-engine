"""
SQLAlchemy ORM Models

Maps core domain objects to relational tables.
Complex nested objects are stored as JSON columns.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    String,
    Boolean,
    Float,
    Integer,
    DateTime,
    Text,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def _utcnow():
    return datetime.now(timezone.utc)


class EventModel(Base):
    __tablename__ = "events"

    id = Column(String, primary_key=True)
    application_id = Column(String, nullable=False, index=True)
    type = Column(String, nullable=False, index=True)
    custom_type = Column(String, nullable=True)
    actor_id = Column(String, nullable=True, index=True)
    actor_type = Column(String, nullable=True)
    target_id = Column(String, nullable=True)
    target_type = Column(String, nullable=True)
    source = Column(String, nullable=True)
    properties = Column(Text, default="{}")
    context = Column(Text, default="{}")
    identity_id = Column(String, nullable=True, index=True)
    processed = Column(Boolean, default=False)
    timestamp = Column(DateTime, default=_utcnow)
    received_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class EntityModel(Base):
    __tablename__ = "entities"

    id = Column(String, primary_key=True)
    application_id = Column(String, nullable=False, index=True)
    type = Column(String, nullable=True)
    type_name = Column(String, nullable=False, index=True)
    status = Column(String, default="active", index=True)
    state = Column(String, nullable=True)
    state_history = Column(Text, default="[]")
    identity_id = Column(String, nullable=True, index=True)
    attributes = Column(Text, default="{}")
    attribute_history = Column(Text, default="[]")
    relationship_ids = Column(Text, default="[]")
    scores = Column(Text, default="{}")
    tags = Column(Text, default="[]")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow)
    last_active_at = Column(DateTime, nullable=True)


class EntityRelationshipModel(Base):
    __tablename__ = "entity_relationships"

    id = Column(String, primary_key=True)
    source_id = Column(String, nullable=False, index=True)
    source_type = Column(String, nullable=False)
    relationship_type = Column(String, nullable=False)
    custom_relationship_type = Column(String, nullable=True)
    target_id = Column(String, nullable=False, index=True)
    target_type = Column(String, nullable=False)
    application_id = Column(String, nullable=False, index=True)
    properties = Column(Text, default="{}")
    created_at = Column(DateTime, default=_utcnow)
    valid_until = Column(DateTime, nullable=True)


class IdentityModel(Base):
    __tablename__ = "identities"

    id = Column(String, primary_key=True)
    status = Column(String, default="anonymous", index=True)
    canonical_email = Column(String, nullable=True, index=True)
    canonical_phone = Column(String, nullable=True)
    touchpoints = Column(Text, default="[]")
    application_ids = Column(Text, default="[]")
    entity_ids = Column(Text, default="{}")
    merged_into = Column(String, nullable=True)
    merged_ids = Column(Text, default="[]")
    traits = Column(Text, default="{}")
    first_seen_at = Column(DateTime, default=_utcnow)
    last_seen_at = Column(DateTime, default=_utcnow)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow)


class BehavioralProfileModel(Base):
    __tablename__ = "behavioral_profiles"

    id = Column(String, primary_key=True)
    identity_id = Column(String, nullable=False, index=True)
    application_id = Column(String, nullable=False, index=True)
    engagement = Column(Text, default="{}")
    interests = Column(Text, default="{}")
    rfm = Column(Text, default="{}")
    communication = Column(Text, default="{}")
    churn = Column(Text, default="{}")
    intent_signals = Column(Text, default="{}")
    event_counts = Column(Text, default="{}")
    traits = Column(Text, default="{}")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow)
    last_event_at = Column(DateTime, nullable=True)


class DecisionModel(Base):
    __tablename__ = "decisions"

    id = Column(String, primary_key=True)
    identity_id = Column(String, nullable=False, index=True)
    application_id = Column(String, nullable=False, index=True)
    entity_id = Column(String, nullable=True)
    entity_type = Column(String, nullable=True)
    action_type = Column(String, nullable=False)
    priority = Column(Integer, default=50)
    status = Column(String, default="pending")
    channel = Column(String, nullable=True)
    payload = Column(Text, default="{}")
    context = Column(Text, default="{}")
    outcome = Column(Text, nullable=True)
    experiment_id = Column(String, nullable=True)
    variant_id = Column(String, nullable=True)
    scheduled_at = Column(DateTime, nullable=True)
    execute_after = Column(DateTime, nullable=True)
    valid_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow)


class PlatformModel(Base):
    __tablename__ = "platforms"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    slug = Column(String, nullable=False, unique=True, index=True)
    api_key_hash = Column(String, nullable=False, index=True)
    api_key_prefix = Column(String, nullable=False)
    status = Column(String, default="active", index=True)
    owner_email = Column(String, nullable=False)
    config_yaml = Column(Text, nullable=True)
    quotas = Column(Text, default="{}")
    metadata_ = Column("metadata", Text, default="{}")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow)


class ActionModel(Base):
    __tablename__ = "actions"

    id = Column(String, primary_key=True)
    decision_id = Column(String, nullable=False, index=True)
    identity_id = Column(String, nullable=False, index=True)
    application_id = Column(String, nullable=False, index=True)
    action_type = Column(String, nullable=False)
    connector_id = Column(String, nullable=True)
    channel = Column(String, nullable=True)
    payload = Column(Text, default="{}")
    status = Column(String, default="queued")
    attempts = Column(Integer, default=0)
    max_attempts = Column(Integer, default=3)
    results = Column(Text, default="[]")
    last_error = Column(String, nullable=True)
    feedback = Column(Text, default="{}")
    context = Column(Text, default="{}")
    scheduled_at = Column(DateTime, nullable=True)
    execute_after = Column(DateTime, nullable=True)
    valid_until = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow)
    dispatched_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)


class ReferralProgramModel(Base):
    __tablename__ = "referral_programs"

    id = Column(String, primary_key=True)
    platform_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    status = Column(String, default="active")
    referrer_reward_type = Column(String, default="credit")
    referrer_reward_value = Column(Float, default=0.0)
    referee_reward_type = Column(String, default="credit")
    referee_reward_value = Column(Float, default=0.0)
    reward_currency = Column(String, nullable=True)
    qualification_event = Column(String, default="USER_REGISTERED")
    double_sided = Column(Boolean, default=True)
    max_referrals_per_user = Column(Integer, default=0)
    code_expiry_days = Column(Integer, default=90)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow)


class ReferralCodeModel(Base):
    __tablename__ = "referral_codes"

    id = Column(String, primary_key=True)
    platform_id = Column(String, nullable=False, index=True)
    referrer_identity_id = Column(String, nullable=False, index=True)
    referrer_entity_id = Column(String, nullable=True)
    code = Column(String, nullable=False, index=True)
    status = Column(String, default="active")
    reward_type = Column(String, default="credit")
    reward_value = Column(Float, default=0.0)
    reward_currency = Column(String, nullable=True)
    max_uses = Column(Integer, default=0)
    current_uses = Column(Integer, default=0)
    expires_at = Column(DateTime, nullable=True)
    metadata_ = Column("metadata", Text, default="{}")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow)


class ReferralModel(Base):
    __tablename__ = "referrals"

    id = Column(String, primary_key=True)
    platform_id = Column(String, nullable=False, index=True)
    referral_code_id = Column(String, nullable=False, index=True)
    referrer_identity_id = Column(String, nullable=False, index=True)
    referee_identity_id = Column(String, nullable=False, index=True)
    referee_entity_id = Column(String, nullable=True)
    status = Column(String, default="pending")
    qualification_event = Column(String, nullable=True)
    referrer_reward = Column(Text, nullable=True)
    referee_reward = Column(Text, nullable=True)
    attributed_at = Column(DateTime, nullable=True)
    qualified_at = Column(DateTime, nullable=True)
    rewarded_at = Column(DateTime, nullable=True)
    metadata_ = Column("metadata", Text, default="{}")
    created_at = Column(DateTime, default=_utcnow)
