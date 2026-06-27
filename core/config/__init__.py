"""
Domain Configuration

Loads YAML domain configs and registers entity types, state machines,
event policies, decision policies, and connectors with the engine.
"""

from .schema import (
    ApplicationConfig,
    ApplicationInfo,
    ConnectorConfig,
    EntityConfig,
    EventsConfig,
    ObjectivesConfig,
    ConstraintsConfig,
    PolicyConditionConfig,
    PolicyActionConfig,
    PolicyConfig,
    StateTransitionConfig,
    StateMachineConfig,
)
from .loader import DomainConfigLoader

__all__ = [
    "ApplicationConfig",
    "ApplicationInfo",
    "ConnectorConfig",
    "EntityConfig",
    "EventsConfig",
    "ObjectivesConfig",
    "ConstraintsConfig",
    "PolicyConditionConfig",
    "PolicyActionConfig",
    "PolicyConfig",
    "StateTransitionConfig",
    "StateMachineConfig",
    "DomainConfigLoader",
]
