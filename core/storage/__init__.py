"""
UGIE Core — Storage Module

Persistent storage layer backed by SQLAlchemy.
Provides drop-in replacements for in-memory repositories.
"""

from .database import init_db, get_session, get_engine
from .models import (
    EventModel,
    EntityModel,
    EntityRelationshipModel,
    IdentityModel,
    BehavioralProfileModel,
    DecisionModel,
    ActionModel,
)
from .repositories import (
    SqlEntityRepository,
    SqlIdentityGraph,
    SqlBehaviorRepository,
)

__all__ = [
    "init_db",
    "get_session",
    "get_engine",
    "EventModel",
    "EntityModel",
    "EntityRelationshipModel",
    "IdentityModel",
    "BehavioralProfileModel",
    "DecisionModel",
    "ActionModel",
    "SqlEntityRepository",
    "SqlIdentityGraph",
    "SqlBehaviorRepository",
]
