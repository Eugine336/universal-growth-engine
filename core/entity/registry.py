"""
Entity Registry

Applications register their entity type definitions here.
The registry validates incoming entity data against those definitions
and enforces required attributes and allowed states.

Example registration (from domain config):
    registry.register(EntityTypeDefinition(
        application_id="ucmc",
        type_name="Seller",
        required_attributes=["display_name", "category"],
        allowed_states=["onboarding", "active", "suspended"],
        initial_state="onboarding",
    ))
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class EntityTypeDefinition:
    """
    Definition of a domain entity type for a specific application.

    Applications register these to teach the engine what their
    entities look like.
    """
    application_id: str
    type_name: str                              # e.g. "Buyer", "Seller", "Trader"
    description: str = ""
    required_attributes: List[str] = field(default_factory=list)
    optional_attributes: List[str] = field(default_factory=list)
    allowed_states: List[str] = field(default_factory=list)
    initial_state: Optional[str] = None
    is_person: bool = False                     # True if this maps to a human identity
    is_asset: bool = False                      # True if this is a tradeable/purchasable item
    allowed_relationship_types: List[str] = field(default_factory=list)

    def key(self) -> str:
        return f"{self.application_id}:{self.type_name}"


@dataclass
class ValidationResult:
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add_error(self, msg: str) -> "ValidationResult":
        self.errors.append(msg)
        self.valid = False
        return self

    def add_warning(self, msg: str) -> "ValidationResult":
        self.warnings.append(msg)
        return self


class EntityRegistry:
    """
    Maintains entity type definitions for all registered applications.

    Usage:
        registry = EntityRegistry()

        registry.register(EntityTypeDefinition(
            application_id="ucmc",
            type_name="Seller",
            required_attributes=["display_name", "category"],
            allowed_states=["onboarding", "active", "suspended"],
            initial_state="onboarding",
            is_person=True,
        ))

        definition = registry.get("ucmc", "Seller")
    """

    def __init__(self):
        # key: "application_id:type_name" → EntityTypeDefinition
        self._definitions: Dict[str, EntityTypeDefinition] = {}
        self._seed_builtin_types()
        logger.info("EntityRegistry initialized")

    def register(self, definition: EntityTypeDefinition) -> None:
        """Register an entity type definition for an application."""
        key = definition.key()
        self._definitions[key] = definition
        logger.info(
            f"Registered entity type | app={definition.application_id} "
            f"type={definition.type_name} "
            f"states={definition.allowed_states}"
        )

    def get(self, application_id: str, type_name: str) -> Optional[EntityTypeDefinition]:
        """Retrieve a definition by application + type name."""
        return self._definitions.get(f"{application_id}:{type_name}")

    def list_for_application(self, application_id: str) -> List[EntityTypeDefinition]:
        """Return all entity type definitions for an application."""
        return [
            d for d in self._definitions.values()
            if d.application_id == application_id
        ]

    def validate_entity(self, entity) -> ValidationResult:
        """
        Validate an entity against its registered type definition.
        If no definition exists, validation passes with a warning.
        """
        result = ValidationResult(valid=True)
        definition = self.get(entity.application_id, entity.type_name)

        if definition is None:
            result.add_warning(
                f"No type definition registered for "
                f"'{entity.application_id}:{entity.type_name}'. "
                f"Validation skipped."
            )
            return result

        # Check required attributes
        for attr in definition.required_attributes:
            if attr not in entity.attributes or entity.attributes[attr] is None:
                result.add_error(
                    f"Required attribute '{attr}' missing for entity type "
                    f"'{entity.type_name}'"
                )

        # Check state is valid
        if entity.state and definition.allowed_states:
            if entity.state not in definition.allowed_states:
                result.add_error(
                    f"State '{entity.state}' is not in allowed states "
                    f"{definition.allowed_states} for type '{entity.type_name}'"
                )

        return result

    def initial_state_for(self, application_id: str, type_name: str) -> Optional[str]:
        """Return the initial state for an entity type, if defined."""
        definition = self.get(application_id, type_name)
        return definition.initial_state if definition else None

    def is_person_type(self, application_id: str, type_name: str) -> bool:
        definition = self.get(application_id, type_name)
        return definition.is_person if definition else False

    # ------------------------------------------------------------------
    # Built-in types — seeded so engine works without explicit registration
    # ------------------------------------------------------------------

    def _seed_builtin_types(self) -> None:
        """
        Seed common entity types that work across all applications.
        Applications can override these with more specific definitions.
        """
        builtins = [
            EntityTypeDefinition(
                application_id="*",
                type_name="User",
                description="A generic human user",
                required_attributes=["email"],
                allowed_states=["registered", "active", "churned", "suspended"],
                initial_state="registered",
                is_person=True,
            ),
            EntityTypeDefinition(
                application_id="*",
                type_name="Organization",
                description="A company or org",
                required_attributes=["name"],
                allowed_states=["active", "inactive", "suspended"],
                initial_state="active",
            ),
        ]
        for d in builtins:
            self._definitions[d.key()] = d
