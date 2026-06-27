"""
Domain Configuration Schema

Pydantic models for parsing YAML domain configuration files.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ApplicationInfo(BaseModel):
    id: str
    name: str
    category: str = ""


class EntityConfig(BaseModel):
    type_name: str
    description: str = ""
    is_person: bool = False
    is_asset: bool = False
    required_attributes: List[str] = Field(default_factory=list)
    optional_attributes: List[str] = Field(default_factory=list)
    allowed_states: List[str] = Field(default_factory=list)
    initial_state: Optional[str] = None
    allowed_relationship_types: List[str] = Field(default_factory=list)


class EventsConfig(BaseModel):
    allowed: List[str] = Field(default_factory=list)
    blocked: List[str] = Field(default_factory=list)
    require_actor: bool = True
    max_properties_size_bytes: int = 65536


class ObjectivesConfig(BaseModel):
    primary: str = ""
    secondary: List[str] = Field(default_factory=list)


class ConstraintsConfig(BaseModel):
    regions: List[str] = Field(default_factory=list)
    compliance: List[str] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)


class StateTransitionConfig(BaseModel):
    from_state: str = Field(alias="from")
    to_state: str = Field(alias="to")
    trigger_events: List[str] = Field(default_factory=list)
    label: str = ""

    model_config = {"populate_by_name": True}


class StateMachineConfig(BaseModel):
    type_name: str
    initial_state: str
    states: List[str] = Field(default_factory=list)
    transitions: List[StateTransitionConfig] = Field(default_factory=list)


class PolicyConditionConfig(BaseModel):
    field: str
    operator: str
    value: Any


class PolicyActionConfig(BaseModel):
    action_type: str
    channel: Optional[str] = None
    priority: int = 50
    payload_template: Dict[str, Any] = Field(default_factory=dict)
    delay_hours: float = 0.0
    valid_hours: float = 24.0


class PolicyConfig(BaseModel):
    name: str
    description: str = ""
    trigger_events: List[str] = Field(default_factory=list)
    conditions: List[PolicyConditionConfig] = Field(default_factory=list)
    condition_logic: str = "AND"
    target_entity_types: List[str] = Field(default_factory=list)
    target_rfm_segments: List[str] = Field(default_factory=list)
    target_engagement_tiers: List[str] = Field(default_factory=list)
    action: PolicyActionConfig
    cooldown_hours: float = 24.0
    max_executions_per_identity: int = 0
    abort_if_events: List[str] = Field(default_factory=list)


class ConnectorConfig(BaseModel):
    id: str
    name: str
    action_types: List[str] = Field(default_factory=list)
    webhook_url: str = ""
    headers: Dict[str, str] = Field(default_factory=dict)
    transformer: str = "generic_webhook"
    timeout_seconds: float = 30.0


class ReferralProgramConfig(BaseModel):
    name: str
    referrer_reward_type: str = "credit"
    referrer_reward_value: float = 0.0
    referee_reward_type: str = "credit"
    referee_reward_value: float = 0.0
    reward_currency: Optional[str] = None
    qualification_event: str = "USER_REGISTERED"
    double_sided: bool = True
    max_referrals_per_user: int = 0
    code_expiry_days: int = 90


class ApplicationConfig(BaseModel):
    application: ApplicationInfo
    entities: List[EntityConfig] = Field(default_factory=list)
    events: Optional[EventsConfig] = None
    objectives: Optional[ObjectivesConfig] = None
    kpis: List[str] = Field(default_factory=list)
    constraints: Optional[ConstraintsConfig] = None
    policies: List[PolicyConfig] = Field(default_factory=list)
    state_machines: List[StateMachineConfig] = Field(default_factory=list)
    connectors: List[ConnectorConfig] = Field(default_factory=list)
    referral_program: Optional[ReferralProgramConfig] = None
