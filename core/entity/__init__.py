"""
UGIE Core — Entity Module

Responsibilities:
- Define the universal entity model
- Maintain an entity registry per application
- Track entity state machines
- Manage entity relationships
- Keep entity attribute history
"""

from .schema import Entity, EntityType, EntityStatus, EntityRelationship, RelationshipType
from .registry import EntityRegistry
from .state import EntityStateMachine, StateTransition
from .repository import EntityRepository

__all__ = [
    "Entity",
    "EntityType",
    "EntityStatus",
    "EntityRelationship",
    "RelationshipType",
    "EntityRegistry",
    "EntityStateMachine",
    "StateTransition",
    "EntityRepository",
]
