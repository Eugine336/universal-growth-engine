"""
Identity Graph

The persistent store of all identities and their relationships.

Maintains two indexes for fast lookup:
1. By identity ID
2. By touchpoint key (email:x, device_id:y, google:z, etc.)

In production this would be backed by a graph database (Neo4j)
or a fast KV store (Redis) with a relational store for durability.
This implementation uses in-memory dicts as the interface contract.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from .schema import Identity, IdentityTouchpoint, TouchpointType

logger = logging.getLogger(__name__)


class IdentityGraph:
    """
    In-memory identity graph with touchpoint-based lookup indexes.

    Interface is database-agnostic — swap the internals for
    Redis + Postgres or Neo4j in production without changing callers.
    """

    def __init__(self):
        # Primary store: identity_id → Identity
        self._identities: Dict[str, Identity] = {}

        # Touchpoint index: touchpoint_key → identity_id
        # e.g. "email:user@example.com" → "identity_abc"
        self._touchpoint_index: Dict[str, str] = {}

        # Entity index: "application_id:entity_id" → identity_id
        self._entity_index: Dict[str, str] = {}

        logger.info("IdentityGraph initialized")

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def save(self, identity: Identity) -> Identity:
        """Persist an identity and rebuild its indexes."""
        self._identities[identity.id] = identity

        # Index all touchpoints
        for tp in identity.touchpoints:
            self._touchpoint_index[tp.key()] = identity.id

        # Index entity mappings
        for app_id, entity_id in identity.entity_ids.items():
            self._entity_index[f"{app_id}:{entity_id}"] = identity.id

        logger.debug(f"Saved identity {identity.id} | touchpoints={len(identity.touchpoints)}")
        return identity

    def delete(self, identity_id: str) -> bool:
        """Remove an identity and clean up its indexes."""
        identity = self._identities.pop(identity_id, None)
        if not identity:
            return False

        # Clean touchpoint index
        for tp in identity.touchpoints:
            self._touchpoint_index.pop(tp.key(), None)

        # Clean entity index
        for app_id, entity_id in identity.entity_ids.items():
            self._entity_index.pop(f"{app_id}:{entity_id}", None)

        return True

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, identity_id: str) -> Optional[Identity]:
        """Fetch identity by ID."""
        return self._identities.get(identity_id)

    def find_by_touchpoint(self, touchpoint: IdentityTouchpoint) -> Optional[Identity]:
        """Find an identity by a touchpoint key."""
        identity_id = self._touchpoint_index.get(touchpoint.key())
        if identity_id:
            return self._identities.get(identity_id)
        return None

    def find_by_touchpoint_key(self, key: str) -> Optional[Identity]:
        """Find by raw touchpoint key string e.g. 'email:user@example.com'."""
        identity_id = self._touchpoint_index.get(key)
        if identity_id:
            return self._identities.get(identity_id)
        return None

    def find_by_entity(self, application_id: str, entity_id: str) -> Optional[Identity]:
        """Find an identity by its domain entity mapping."""
        identity_id = self._entity_index.get(f"{application_id}:{entity_id}")
        if identity_id:
            return self._identities.get(identity_id)
        return None

    def find_by_email(self, email: str) -> Optional[Identity]:
        return self.find_by_touchpoint_key(f"email:{email.lower().strip()}")

    def find_by_phone(self, phone: str) -> Optional[Identity]:
        return self.find_by_touchpoint_key(f"phone:{phone.strip()}")

    def find_by_device(self, device_id: str) -> Optional[Identity]:
        return self.find_by_touchpoint_key(f"device_id:{device_id.strip()}")

    def list_by_application(self, application_id: str) -> List[Identity]:
        """Return all identities seen in a given application."""
        return [
            i for i in self._identities.values()
            if application_id in i.application_ids
        ]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> Dict:
        total = len(self._identities)
        anonymous = sum(1 for i in self._identities.values() if i.is_anonymous())
        merged = sum(1 for i in self._identities.values() if i.is_merged())
        return {
            "total_identities": total,
            "active": total - anonymous - merged,
            "anonymous": anonymous,
            "merged": merged,
            "touchpoint_index_size": len(self._touchpoint_index),
            "entity_index_size": len(self._entity_index),
        }

    def size(self) -> int:
        return len(self._identities)
