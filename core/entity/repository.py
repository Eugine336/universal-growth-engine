"""
Entity Repository

The persistent store for all entities and relationships.

Maintains indexes for fast lookup by:
- Entity ID
- Application + type
- Identity ID
- State
- Tags
- Attribute values (simple equality)

In production this maps to a relational DB (Postgres) + search index (Elasticsearch).
This implementation uses in-memory dicts as the interface contract.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, List, Optional

from .schema import Entity, EntityRelationship, EntityStatus

logger = logging.getLogger(__name__)


class EntityRepository:
    """
    In-memory entity and relationship store with multi-index lookup.

    Interface is database-agnostic. Swap internals for Postgres +
    Elasticsearch in production without changing callers.
    """

    def __init__(self):
        # Primary store
        self._entities: Dict[str, Entity] = {}
        self._relationships: Dict[str, EntityRelationship] = {}

        # Indexes
        self._by_application_type: Dict[str, List[str]] = defaultdict(list)
        self._by_identity: Dict[str, List[str]] = defaultdict(list)
        self._by_state: Dict[str, List[str]] = defaultdict(list)
        self._by_tag: Dict[str, List[str]] = defaultdict(list)

        # Relationship indexes
        self._rels_by_source: Dict[str, List[str]] = defaultdict(list)
        self._rels_by_target: Dict[str, List[str]] = defaultdict(list)

        logger.info("EntityRepository initialized")

    # ------------------------------------------------------------------
    # Entity CRUD
    # ------------------------------------------------------------------

    def save(self, entity: Entity) -> Entity:
        """Persist an entity and rebuild its indexes."""
        existing = self._entities.get(entity.id)
        if existing:
            self._remove_from_indexes(existing)

        self._entities[entity.id] = entity
        self._build_indexes(entity)
        logger.debug(f"Saved entity {entity.id} ({entity.type_name})")
        return entity

    def get(self, entity_id: str) -> Optional[Entity]:
        return self._entities.get(entity_id)

    def delete(self, entity_id: str) -> bool:
        entity = self._entities.pop(entity_id, None)
        if entity:
            self._remove_from_indexes(entity)
            return True
        return False

    def soft_delete(self, entity_id: str) -> Optional[Entity]:
        entity = self._entities.get(entity_id)
        if entity:
            entity.status = EntityStatus.DELETED
            self.save(entity)
        return entity

    # ------------------------------------------------------------------
    # Entity Queries
    # ------------------------------------------------------------------

    def find_by_application_and_type(
        self,
        application_id: str,
        type_name: str,
        status: Optional[EntityStatus] = None,
    ) -> List[Entity]:
        ids = self._by_application_type.get(f"{application_id}:{type_name}", [])
        entities = [self._entities[i] for i in ids if i in self._entities]
        if status:
            entities = [e for e in entities if e.status == status]
        return entities

    def find_by_identity(self, identity_id: str) -> List[Entity]:
        ids = self._by_identity.get(identity_id, [])
        return [self._entities[i] for i in ids if i in self._entities]

    def find_by_state(
        self,
        application_id: str,
        type_name: str,
        state: str,
    ) -> List[Entity]:
        state_key = f"{application_id}:{type_name}:{state}"
        ids = self._by_state.get(state_key, [])
        return [self._entities[i] for i in ids if i in self._entities]

    def find_by_tag(self, tag: str, application_id: Optional[str] = None) -> List[Entity]:
        ids = self._by_tag.get(tag, [])
        entities = [self._entities[i] for i in ids if i in self._entities]
        if application_id:
            entities = [e for e in entities if e.application_id == application_id]
        return entities

    def find_by_attribute(
        self,
        application_id: str,
        type_name: str,
        key: str,
        value,
    ) -> List[Entity]:
        """Simple attribute equality scan — use a search index in production."""
        entities = self.find_by_application_and_type(application_id, type_name)
        return [e for e in entities if e.attributes.get(key) == value]

    def count(
        self,
        application_id: Optional[str] = None,
        type_name: Optional[str] = None,
        status: Optional[EntityStatus] = None,
    ) -> int:
        entities = list(self._entities.values())
        if application_id:
            entities = [e for e in entities if e.application_id == application_id]
        if type_name:
            entities = [e for e in entities if e.type_name == type_name]
        if status:
            entities = [e for e in entities if e.status == status]
        return len(entities)

    # ------------------------------------------------------------------
    # Relationship CRUD
    # ------------------------------------------------------------------

    def save_relationship(self, rel: EntityRelationship) -> EntityRelationship:
        self._relationships[rel.id] = rel
        self._rels_by_source[rel.source_id].append(rel.id)
        self._rels_by_target[rel.target_id].append(rel.id)
        return rel

    def get_relationship(self, rel_id: str) -> Optional[EntityRelationship]:
        return self._relationships.get(rel_id)

    def delete_relationship(self, rel_id: str) -> bool:
        rel = self._relationships.pop(rel_id, None)
        if rel:
            self._rels_by_source[rel.source_id] = [
                r for r in self._rels_by_source[rel.source_id] if r != rel_id
            ]
            self._rels_by_target[rel.target_id] = [
                r for r in self._rels_by_target[rel.target_id] if r != rel_id
            ]
            return True
        return False

    def get_relationships_from(
        self,
        source_id: str,
        relationship_type: Optional[str] = None,
    ) -> List[EntityRelationship]:
        ids = self._rels_by_source.get(source_id, [])
        rels = [self._relationships[i] for i in ids if i in self._relationships]
        if relationship_type:
            rels = [r for r in rels if r.label() == relationship_type]
        return [r for r in rels if r.is_active()]

    def get_relationships_to(
        self,
        target_id: str,
        relationship_type: Optional[str] = None,
    ) -> List[EntityRelationship]:
        ids = self._rels_by_target.get(target_id, [])
        rels = [self._relationships[i] for i in ids if i in self._relationships]
        if relationship_type:
            rels = [r for r in rels if r.label() == relationship_type]
        return [r for r in rels if r.is_active()]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> Dict:
        total = len(self._entities)
        by_status = defaultdict(int)
        for e in self._entities.values():
            by_status[e.status.value] += 1
        return {
            "total_entities": total,
            "total_relationships": len(self._relationships),
            "by_status": dict(by_status),
        }

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    def _build_indexes(self, entity: Entity) -> None:
        # Application + type index
        key = f"{entity.application_id}:{entity.type_name}"
        if entity.id not in self._by_application_type[key]:
            self._by_application_type[key].append(entity.id)

        # Identity index
        if entity.identity_id:
            if entity.id not in self._by_identity[entity.identity_id]:
                self._by_identity[entity.identity_id].append(entity.id)

        # State index
        if entity.state:
            state_key = f"{entity.application_id}:{entity.type_name}:{entity.state}"
            if entity.id not in self._by_state[state_key]:
                self._by_state[state_key].append(entity.id)

        # Tag index
        for tag in entity.tags:
            if entity.id not in self._by_tag[tag]:
                self._by_tag[tag].append(entity.id)

    def _remove_from_indexes(self, entity: Entity) -> None:
        key = f"{entity.application_id}:{entity.type_name}"
        self._by_application_type[key] = [
            i for i in self._by_application_type[key] if i != entity.id
        ]
        if entity.identity_id:
            self._by_identity[entity.identity_id] = [
                i for i in self._by_identity[entity.identity_id] if i != entity.id
            ]
        if entity.state:
            state_key = f"{entity.application_id}:{entity.type_name}:{entity.state}"
            self._by_state[state_key] = [
                i for i in self._by_state[state_key] if i != entity.id
            ]
        for tag in entity.tags:
            self._by_tag[tag] = [i for i in self._by_tag[tag] if i != entity.id]
