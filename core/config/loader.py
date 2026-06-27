"""
Domain Configuration Loader

Reads YAML domain configs and registers entity types, state machines,
event policies, and decision policies with the engine components.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Optional

import yaml

from core.decision.policy import (
    Policy,
    PolicyAction,
    PolicyCondition,
    PolicyRegistry,
)
from core.decision.schema import ActionType
from core.entity.registry import EntityRegistry, EntityTypeDefinition
from core.entity.state import (
    EntityStateMachine,
    StateMachineDefinition,
    StateTransition,
)
from core.events.validator import ApplicationEventPolicy, EventValidator

from .schema import ApplicationConfig

logger = logging.getLogger(__name__)


class ConfigLoadError(Exception):
    """Raised when a domain config cannot be loaded or parsed."""


class DomainConfigLoader:
    """
    Loads a domain YAML config and registers everything with the engine.

    Usage:
        loader = DomainConfigLoader(
            entity_registry=registry,
            state_machine=state_machine,
            event_validator=validator,
            policy_registry=policy_registry,
        )
        loader.load_file("domain/examples/ucmc/config.yaml")
    """

    def __init__(
        self,
        entity_registry: EntityRegistry,
        state_machine: EntityStateMachine,
        event_validator: EventValidator,
        policy_registry: PolicyRegistry,
    ):
        self._entity_registry = entity_registry
        self._state_machine = state_machine
        self._event_validator = event_validator
        self._policy_registry = policy_registry
        self._loaded_apps: List[str] = []

    @property
    def loaded_applications(self) -> List[str]:
        return list(self._loaded_apps)

    def load_file(self, path: str) -> ApplicationConfig:
        """Load a single YAML config file and register its components."""
        file_path = Path(path)
        if not file_path.exists():
            raise ConfigLoadError(f"Config file not found: {path}")

        try:
            with open(file_path) as f:
                raw = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ConfigLoadError(f"Invalid YAML in {path}: {e}")

        if not isinstance(raw, dict):
            raise ConfigLoadError(f"Config root must be a mapping, got {type(raw).__name__}")

        try:
            config = ApplicationConfig.model_validate(raw)
        except Exception as e:
            raise ConfigLoadError(f"Config validation failed for {path}: {e}")

        app_id = config.application.id
        logger.info(f"Loading domain config | app={app_id} name={config.application.name}")

        self._register_entities(config)
        self._register_state_machines(config)
        self._register_event_policy(config)
        self._register_policies(config)

        self._loaded_apps.append(app_id)
        logger.info(
            f"Domain config loaded | app={app_id} "
            f"entities={len(config.entities)} "
            f"state_machines={len(config.state_machines)} "
            f"policies={len(config.policies)}"
        )
        return config

    def load_directory(self, directory: str) -> List[ApplicationConfig]:
        """Load all config.yaml files found under a directory."""
        dir_path = Path(directory)
        if not dir_path.exists():
            logger.warning(f"Config directory not found: {directory}")
            return []

        configs = []
        for yaml_file in sorted(dir_path.rglob("config.yaml")):
            try:
                configs.append(self.load_file(str(yaml_file)))
            except ConfigLoadError as e:
                logger.error(f"Failed to load {yaml_file}: {e}")

        logger.info(f"Loaded {len(configs)} domain config(s) from {directory}")
        return configs

    def _register_entities(self, config: ApplicationConfig) -> None:
        app_id = config.application.id
        for entity_cfg in config.entities:
            definition = EntityTypeDefinition(
                application_id=app_id,
                type_name=entity_cfg.type_name,
                description=entity_cfg.description,
                required_attributes=entity_cfg.required_attributes,
                optional_attributes=entity_cfg.optional_attributes,
                allowed_states=entity_cfg.allowed_states,
                initial_state=entity_cfg.initial_state,
                is_person=entity_cfg.is_person,
                is_asset=entity_cfg.is_asset,
                allowed_relationship_types=entity_cfg.allowed_relationship_types,
            )
            self._entity_registry.register(definition)

    def _register_state_machines(self, config: ApplicationConfig) -> None:
        app_id = config.application.id
        for sm_cfg in config.state_machines:
            transitions = []
            for t_cfg in sm_cfg.transitions:
                transitions.append(StateTransition(
                    from_state=t_cfg.from_state,
                    to_state=t_cfg.to_state,
                    trigger_events=t_cfg.trigger_events,
                    label=t_cfg.label,
                ))
            definition = StateMachineDefinition(
                application_id=app_id,
                type_name=sm_cfg.type_name,
                initial_state=sm_cfg.initial_state,
                states=sm_cfg.states,
                transitions=transitions,
            )
            self._state_machine.register(definition)

    def _register_event_policy(self, config: ApplicationConfig) -> None:
        if config.events is None:
            return
        app_id = config.application.id
        policy = ApplicationEventPolicy(
            application_id=app_id,
            allowed_events=set(config.events.allowed) if config.events.allowed else set(),
            blocked_events=set(config.events.blocked) if config.events.blocked else set(),
            require_actor=config.events.require_actor,
            max_properties_size_bytes=config.events.max_properties_size_bytes,
        )
        self._event_validator.register_policy(policy)

    def _register_policies(self, config: ApplicationConfig) -> None:
        app_id = config.application.id
        for p_cfg in config.policies:
            conditions = [
                PolicyCondition(
                    field=c.field,
                    operator=c.operator,
                    value=c.value,
                )
                for c in p_cfg.conditions
            ]
            try:
                action_type = ActionType(p_cfg.action.action_type)
            except ValueError:
                logger.warning(
                    f"Unknown action type '{p_cfg.action.action_type}' "
                    f"in policy '{p_cfg.name}', skipping"
                )
                continue

            action = PolicyAction(
                action_type=action_type,
                channel=p_cfg.action.channel,
                priority=p_cfg.action.priority,
                payload_template=p_cfg.action.payload_template,
                delay_hours=p_cfg.action.delay_hours,
                valid_hours=p_cfg.action.valid_hours,
            )
            policy = Policy(
                application_id=app_id,
                name=p_cfg.name,
                description=p_cfg.description,
                trigger_events=p_cfg.trigger_events,
                conditions=conditions,
                condition_logic=p_cfg.condition_logic,
                target_entity_types=p_cfg.target_entity_types,
                target_rfm_segments=p_cfg.target_rfm_segments,
                target_engagement_tiers=p_cfg.target_engagement_tiers,
                action=action,
                cooldown_hours=p_cfg.cooldown_hours,
                max_executions_per_identity=p_cfg.max_executions_per_identity,
                abort_if_events=p_cfg.abort_if_events,
            )
            self._policy_registry.register(policy)
