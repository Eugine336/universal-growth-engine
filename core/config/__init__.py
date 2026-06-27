"""
Domain Configuration

Loads YAML domain configs and registers entity types, state machines,
event policies, and decision policies with the engine.
"""

from .schema import (
    ApplicationConfig,
    ApplicationInfo,
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
