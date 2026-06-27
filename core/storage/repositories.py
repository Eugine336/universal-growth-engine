"""
SQL-backed Repository Implementations

Drop-in replacements for the in-memory repositories.
Each class wraps SQLAlchemy operations but exposes the exact
same method signatures as the in-memory versions.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from core.entity.schema import (
    Entity,
    EntityRelationship,
    EntityStatus,
    EntityType,
    RelationshipType,
    AttributeHistory,
)
from core.identity.schema import (
    Identity,
    IdentityTouchpoint,
    IdentityStatus,
    TouchpointType,
)
from core.behavior.schema import (
    BehavioralProfile,
    EngagementProfile,
    InterestProfile,
    RFMScore,
    CommunicationPreference,
    ChurnSignal,
    IntentSignal,
)

from core.platform.schema import (
    Platform,
    PlatformQuotas,
    PlatformStatus,
)

from .models import (
    EntityModel,
    EntityRelationshipModel,
    IdentityModel,
    BehavioralProfileModel,
    PlatformModel,
)

logger = logging.getLogger(__name__)


def _json_loads(text: Optional[str], default=None):
    if not text:
        return default if default is not None else {}
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else {}


def _json_dumps(obj) -> str:
    return json.dumps(obj, default=str)


def _parse_datetime(val) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val
    if isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return None
    return None


# ======================================================================
# SqlEntityRepository
# ======================================================================

class SqlEntityRepository:

    def __init__(self, session_factory):
        self._session_factory = session_factory
        logger.info("SqlEntityRepository initialized")

    def _session(self) -> Session:
        return self._session_factory()

    # -- Entity CRUD ---------------------------------------------------

    def save(self, entity: Entity) -> Entity:
        session = self._session()
        try:
            model = self._to_model(entity)
            session.merge(model)
            session.commit()
            logger.debug(f"Saved entity {entity.id} ({entity.type_name})")
            return entity
        finally:
            session.close()

    def get(self, entity_id: str) -> Optional[Entity]:
        session = self._session()
        try:
            row = session.get(EntityModel, entity_id)
            return self._from_model(row) if row else None
        finally:
            session.close()

    def delete(self, entity_id: str) -> bool:
        session = self._session()
        try:
            row = session.get(EntityModel, entity_id)
            if row:
                session.delete(row)
                session.commit()
                return True
            return False
        finally:
            session.close()

    def soft_delete(self, entity_id: str) -> Optional[Entity]:
        entity = self.get(entity_id)
        if entity:
            entity.status = EntityStatus.DELETED
            self.save(entity)
        return entity

    # -- Entity Queries ------------------------------------------------

    def find_by_application_and_type(
        self, application_id: str, type_name: str,
        status: Optional[EntityStatus] = None,
    ) -> List[Entity]:
        session = self._session()
        try:
            q = session.query(EntityModel).filter_by(
                application_id=application_id, type_name=type_name
            )
            if status:
                q = q.filter_by(status=status.value)
            return [self._from_model(r) for r in q.all()]
        finally:
            session.close()

    def find_by_identity(self, identity_id: str) -> List[Entity]:
        session = self._session()
        try:
            rows = session.query(EntityModel).filter_by(identity_id=identity_id).all()
            return [self._from_model(r) for r in rows]
        finally:
            session.close()

    def find_by_state(self, application_id: str, type_name: str, state: str) -> List[Entity]:
        session = self._session()
        try:
            rows = session.query(EntityModel).filter_by(
                application_id=application_id, type_name=type_name, state=state
            ).all()
            return [self._from_model(r) for r in rows]
        finally:
            session.close()

    def find_by_tag(self, tag: str, application_id: Optional[str] = None) -> List[Entity]:
        session = self._session()
        try:
            q = session.query(EntityModel)
            if application_id:
                q = q.filter_by(application_id=application_id)
            results = []
            for row in q.all():
                tags = _json_loads(row.tags, [])
                if tag in tags:
                    results.append(self._from_model(row))
            return results
        finally:
            session.close()

    def find_by_attribute(
        self, application_id: str, type_name: str, key: str, value,
    ) -> List[Entity]:
        entities = self.find_by_application_and_type(application_id, type_name)
        return [e for e in entities if e.attributes.get(key) == value]

    def count(
        self, application_id: Optional[str] = None,
        type_name: Optional[str] = None,
        status: Optional[EntityStatus] = None,
    ) -> int:
        session = self._session()
        try:
            q = session.query(EntityModel)
            if application_id:
                q = q.filter_by(application_id=application_id)
            if type_name:
                q = q.filter_by(type_name=type_name)
            if status:
                q = q.filter_by(status=status.value)
            return q.count()
        finally:
            session.close()

    # -- Relationship CRUD ---------------------------------------------

    def save_relationship(self, rel: EntityRelationship) -> EntityRelationship:
        session = self._session()
        try:
            model = EntityRelationshipModel(
                id=rel.id,
                source_id=rel.source_id,
                source_type=rel.source_type,
                relationship_type=rel.relationship_type.value if isinstance(rel.relationship_type, RelationshipType) else rel.relationship_type,
                custom_relationship_type=rel.custom_relationship_type,
                target_id=rel.target_id,
                target_type=rel.target_type,
                application_id=rel.application_id,
                properties=_json_dumps(rel.properties),
                created_at=rel.created_at,
                valid_until=rel.valid_until,
            )
            session.merge(model)
            session.commit()
            return rel
        finally:
            session.close()

    def get_relationship(self, rel_id: str) -> Optional[EntityRelationship]:
        session = self._session()
        try:
            row = session.get(EntityRelationshipModel, rel_id)
            return self._rel_from_model(row) if row else None
        finally:
            session.close()

    def delete_relationship(self, rel_id: str) -> bool:
        session = self._session()
        try:
            row = session.get(EntityRelationshipModel, rel_id)
            if row:
                session.delete(row)
                session.commit()
                return True
            return False
        finally:
            session.close()

    def get_relationships_from(
        self, source_id: str, relationship_type: Optional[str] = None,
    ) -> List[EntityRelationship]:
        session = self._session()
        try:
            q = session.query(EntityRelationshipModel).filter_by(source_id=source_id)
            rels = [self._rel_from_model(r) for r in q.all()]
            if relationship_type:
                rels = [r for r in rels if r.label() == relationship_type]
            return [r for r in rels if r.is_active()]
        finally:
            session.close()

    def get_relationships_to(
        self, target_id: str, relationship_type: Optional[str] = None,
    ) -> List[EntityRelationship]:
        session = self._session()
        try:
            q = session.query(EntityRelationshipModel).filter_by(target_id=target_id)
            rels = [self._rel_from_model(r) for r in q.all()]
            if relationship_type:
                rels = [r for r in rels if r.label() == relationship_type]
            return [r for r in rels if r.is_active()]
        finally:
            session.close()

    def stats(self) -> Dict:
        session = self._session()
        try:
            total = session.query(EntityModel).count()
            rels = session.query(EntityRelationshipModel).count()
            return {
                "total_entities": total,
                "total_relationships": rels,
                "by_status": {},
            }
        finally:
            session.close()

    # -- Conversion helpers --------------------------------------------

    def _to_model(self, entity: Entity) -> EntityModel:
        return EntityModel(
            id=entity.id,
            application_id=entity.application_id,
            type=entity.type.value if isinstance(entity.type, EntityType) else entity.type,
            type_name=entity.type_name,
            status=entity.status.value if isinstance(entity.status, EntityStatus) else entity.status,
            state=entity.state,
            state_history=_json_dumps(entity.state_history),
            identity_id=entity.identity_id,
            attributes=_json_dumps(entity.attributes),
            attribute_history=_json_dumps([h.model_dump() for h in entity.attribute_history]),
            relationship_ids=_json_dumps(entity.relationship_ids),
            scores=_json_dumps(entity.scores),
            tags=_json_dumps(entity.tags),
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            last_active_at=entity.last_active_at,
        )

    def _from_model(self, row: EntityModel) -> Entity:
        attr_history_raw = _json_loads(row.attribute_history, [])
        attr_history = []
        for h in attr_history_raw:
            changed_at = _parse_datetime(h.get("changed_at"))
            attr_history.append(AttributeHistory(
                key=h["key"],
                old_value=h.get("old_value"),
                new_value=h["new_value"],
                changed_at=changed_at or datetime.now(timezone.utc),
                changed_by=h.get("changed_by"),
            ))
        return Entity(
            id=row.id,
            application_id=row.application_id,
            type=EntityType(row.type) if row.type else EntityType.CUSTOM,
            type_name=row.type_name,
            status=EntityStatus(row.status),
            state=row.state,
            state_history=_json_loads(row.state_history, []),
            identity_id=row.identity_id,
            attributes=_json_loads(row.attributes, {}),
            attribute_history=attr_history,
            relationship_ids=_json_loads(row.relationship_ids, []),
            scores=_json_loads(row.scores, {}),
            tags=_json_loads(row.tags, []),
            created_at=_parse_datetime(row.created_at) or datetime.now(timezone.utc),
            updated_at=_parse_datetime(row.updated_at) or datetime.now(timezone.utc),
            last_active_at=_parse_datetime(row.last_active_at),
        )

    def _rel_from_model(self, row: EntityRelationshipModel) -> EntityRelationship:
        return EntityRelationship(
            id=row.id,
            source_id=row.source_id,
            source_type=row.source_type,
            relationship_type=RelationshipType(row.relationship_type),
            custom_relationship_type=row.custom_relationship_type,
            target_id=row.target_id,
            target_type=row.target_type,
            application_id=row.application_id,
            properties=_json_loads(row.properties, {}),
            created_at=_parse_datetime(row.created_at) or datetime.now(timezone.utc),
            valid_until=_parse_datetime(row.valid_until),
        )


# ======================================================================
# SqlIdentityGraph
# ======================================================================

class SqlIdentityGraph:

    def __init__(self, session_factory):
        self._session_factory = session_factory
        logger.info("SqlIdentityGraph initialized")

    def _session(self) -> Session:
        return self._session_factory()

    # -- Write ---------------------------------------------------------

    def save(self, identity: Identity) -> Identity:
        session = self._session()
        try:
            model = self._to_model(identity)
            session.merge(model)
            session.commit()
            logger.debug(f"Saved identity {identity.id}")
            return identity
        finally:
            session.close()

    def delete(self, identity_id: str) -> bool:
        session = self._session()
        try:
            row = session.get(IdentityModel, identity_id)
            if not row:
                return False
            session.delete(row)
            session.commit()
            return True
        finally:
            session.close()

    # -- Read ----------------------------------------------------------

    def get(self, identity_id: str) -> Optional[Identity]:
        session = self._session()
        try:
            row = session.get(IdentityModel, identity_id)
            return self._from_model(row) if row else None
        finally:
            session.close()

    def find_by_touchpoint(self, touchpoint: IdentityTouchpoint) -> Optional[Identity]:
        return self.find_by_touchpoint_key(touchpoint.key())

    def find_by_touchpoint_key(self, key: str) -> Optional[Identity]:
        session = self._session()
        try:
            for row in session.query(IdentityModel).all():
                tps = _json_loads(row.touchpoints, [])
                for tp in tps:
                    tp_type = tp.get("type", "")
                    tp_val = tp.get("value", "")
                    constructed_key = f"{tp_type}:{tp_val.lower().strip()}"
                    if constructed_key == key:
                        return self._from_model(row)
            return None
        finally:
            session.close()

    def find_by_entity(self, application_id: str, entity_id: str) -> Optional[Identity]:
        session = self._session()
        try:
            for row in session.query(IdentityModel).all():
                entity_ids = _json_loads(row.entity_ids, {})
                if entity_ids.get(application_id) == entity_id:
                    return self._from_model(row)
            return None
        finally:
            session.close()

    def find_by_email(self, email: str) -> Optional[Identity]:
        normalized = email.lower().strip()
        session = self._session()
        try:
            row = session.query(IdentityModel).filter_by(canonical_email=normalized).first()
            if row:
                return self._from_model(row)
            return self.find_by_touchpoint_key(f"email:{normalized}")
        finally:
            session.close()

    def find_by_phone(self, phone: str) -> Optional[Identity]:
        return self.find_by_touchpoint_key(f"phone:{phone.strip()}")

    def find_by_device(self, device_id: str) -> Optional[Identity]:
        return self.find_by_touchpoint_key(f"device_id:{device_id.strip()}")

    def list_by_application(self, application_id: str) -> List[Identity]:
        session = self._session()
        try:
            results = []
            for row in session.query(IdentityModel).all():
                app_ids = _json_loads(row.application_ids, [])
                if application_id in app_ids:
                    results.append(self._from_model(row))
            return results
        finally:
            session.close()

    # -- Stats ---------------------------------------------------------

    def stats(self) -> Dict:
        session = self._session()
        try:
            total = session.query(IdentityModel).count()
            anonymous = session.query(IdentityModel).filter_by(status="anonymous").count()
            merged = session.query(IdentityModel).filter_by(status="merged").count()
            return {
                "total_identities": total,
                "active": total - anonymous - merged,
                "anonymous": anonymous,
                "merged": merged,
                "touchpoint_index_size": 0,
                "entity_index_size": 0,
            }
        finally:
            session.close()

    def size(self) -> int:
        session = self._session()
        try:
            return session.query(IdentityModel).count()
        finally:
            session.close()

    # -- Conversion helpers --------------------------------------------

    def _to_model(self, identity: Identity) -> IdentityModel:
        touchpoints_data = []
        for tp in identity.touchpoints:
            touchpoints_data.append(tp.model_dump())
        return IdentityModel(
            id=identity.id,
            status=identity.status.value if isinstance(identity.status, IdentityStatus) else identity.status,
            canonical_email=identity.canonical_email,
            canonical_phone=identity.canonical_phone,
            touchpoints=_json_dumps(touchpoints_data),
            application_ids=_json_dumps(identity.application_ids),
            entity_ids=_json_dumps(identity.entity_ids),
            merged_into=identity.merged_into,
            merged_ids=_json_dumps(identity.merged_ids),
            traits=_json_dumps(identity.traits),
            first_seen_at=identity.first_seen_at,
            last_seen_at=identity.last_seen_at,
            created_at=identity.created_at,
            updated_at=identity.updated_at,
        )

    def _from_model(self, row: IdentityModel) -> Identity:
        touchpoints_data = _json_loads(row.touchpoints, [])
        touchpoints = []
        for tp_data in touchpoints_data:
            tp_type = tp_data.get("type", "custom")
            if isinstance(tp_type, str):
                tp_type = TouchpointType(tp_type)
            first_seen = _parse_datetime(tp_data.get("first_seen_at"))
            last_seen = _parse_datetime(tp_data.get("last_seen_at"))
            touchpoints.append(IdentityTouchpoint(
                id=tp_data.get("id", ""),
                type=tp_type,
                value=tp_data.get("value", ""),
                application_id=tp_data.get("application_id"),
                verified=tp_data.get("verified", False),
                first_seen_at=first_seen or datetime.now(timezone.utc),
                last_seen_at=last_seen or datetime.now(timezone.utc),
                metadata=tp_data.get("metadata", {}),
            ))
        return Identity(
            id=row.id,
            status=IdentityStatus(row.status),
            touchpoints=touchpoints,
            canonical_email=row.canonical_email,
            canonical_phone=row.canonical_phone,
            application_ids=_json_loads(row.application_ids, []),
            entity_ids=_json_loads(row.entity_ids, {}),
            merged_into=row.merged_into,
            merged_ids=_json_loads(row.merged_ids, []),
            traits=_json_loads(row.traits, {}),
            first_seen_at=_parse_datetime(row.first_seen_at) or datetime.now(timezone.utc),
            last_seen_at=_parse_datetime(row.last_seen_at) or datetime.now(timezone.utc),
            created_at=_parse_datetime(row.created_at) or datetime.now(timezone.utc),
            updated_at=_parse_datetime(row.updated_at) or datetime.now(timezone.utc),
        )


# ======================================================================
# SqlBehaviorRepository
# ======================================================================

class SqlBehaviorRepository:

    def __init__(self, session_factory):
        self._session_factory = session_factory
        logger.info("SqlBehaviorRepository initialized")

    def _session(self) -> Session:
        return self._session_factory()

    def _key(self, identity_id: str, application_id: str) -> str:
        return f"{application_id}:{identity_id}"

    def save(self, profile: BehavioralProfile) -> BehavioralProfile:
        session = self._session()
        try:
            model = self._to_model(profile)
            session.merge(model)
            session.commit()
            logger.debug(f"Saved behavioral profile | identity={profile.identity_id}")
            return profile
        finally:
            session.close()

    def get(self, identity_id: str, application_id: str) -> Optional[BehavioralProfile]:
        session = self._session()
        try:
            row = session.query(BehavioralProfileModel).filter_by(
                identity_id=identity_id, application_id=application_id
            ).first()
            return self._from_model(row) if row else None
        finally:
            session.close()

    def get_or_create(self, identity_id: str, application_id: str) -> BehavioralProfile:
        profile = self.get(identity_id, application_id)
        if not profile:
            profile = BehavioralProfile(
                identity_id=identity_id,
                application_id=application_id,
            )
            self.save(profile)
            logger.info(f"Created new behavioral profile | identity={identity_id}")
        return profile

    def delete(self, identity_id: str, application_id: str) -> bool:
        session = self._session()
        try:
            row = session.query(BehavioralProfileModel).filter_by(
                identity_id=identity_id, application_id=application_id
            ).first()
            if row:
                session.delete(row)
                session.commit()
                return True
            return False
        finally:
            session.close()

    def list_by_application(self, application_id: str) -> List[BehavioralProfile]:
        session = self._session()
        try:
            rows = session.query(BehavioralProfileModel).filter_by(
                application_id=application_id
            ).all()
            return [self._from_model(r) for r in rows]
        finally:
            session.close()

    def find_by_churn_risk(self, application_id: str, risk_level: str) -> List[BehavioralProfile]:
        return [
            p for p in self.list_by_application(application_id)
            if p.churn.risk_level == risk_level
        ]

    def find_by_rfm_segment(self, application_id: str, segment: str) -> List[BehavioralProfile]:
        return [
            p for p in self.list_by_application(application_id)
            if p.rfm.segment == segment
        ]

    def find_by_engagement_tier(self, application_id: str, tier: str) -> List[BehavioralProfile]:
        return [
            p for p in self.list_by_application(application_id)
            if p.engagement.tier == tier
        ]

    def find_with_intent(
        self, application_id: str, signal_type: str, min_strength: float = 0.5,
    ) -> List[BehavioralProfile]:
        results = []
        for p in self.list_by_application(application_id):
            signal = p.get_intent_signal(signal_type)
            if signal and signal.strength >= min_strength:
                results.append(p)
        return results

    def stats(self, application_id: Optional[str] = None) -> Dict:
        profiles = (
            self.list_by_application(application_id)
            if application_id
            else self._all_profiles()
        )
        tiers = {}
        segments = {}
        churn_levels = {}
        for p in profiles:
            tiers[p.engagement.tier] = tiers.get(p.engagement.tier, 0) + 1
            segments[p.rfm.segment] = segments.get(p.rfm.segment, 0) + 1
            churn_levels[p.churn.risk_level] = churn_levels.get(p.churn.risk_level, 0) + 1
        return {
            "total_profiles": len(profiles),
            "engagement_tiers": tiers,
            "rfm_segments": segments,
            "churn_risk_levels": churn_levels,
        }

    def _all_profiles(self) -> List[BehavioralProfile]:
        session = self._session()
        try:
            rows = session.query(BehavioralProfileModel).all()
            return [self._from_model(r) for r in rows]
        finally:
            session.close()

    # -- Conversion helpers --------------------------------------------

    def _to_model(self, profile: BehavioralProfile) -> BehavioralProfileModel:
        return BehavioralProfileModel(
            id=profile.id,
            identity_id=profile.identity_id,
            application_id=profile.application_id,
            engagement=_json_dumps(profile.engagement.model_dump()),
            interests=_json_dumps(profile.interests.model_dump()),
            rfm=_json_dumps(profile.rfm.model_dump()),
            communication=_json_dumps(profile.communication.model_dump()),
            churn=_json_dumps(profile.churn.model_dump()),
            intent_signals=_json_dumps({k: v.model_dump() for k, v in profile.intent_signals.items()}),
            event_counts=_json_dumps(profile.event_counts),
            traits=_json_dumps(profile.traits),
            created_at=profile.created_at,
            updated_at=profile.updated_at,
            last_event_at=profile.last_event_at,
        )

    def _from_model(self, row: BehavioralProfileModel) -> BehavioralProfile:
        engagement_data = _json_loads(row.engagement, {})
        interests_data = _json_loads(row.interests, {})
        rfm_data = _json_loads(row.rfm, {})
        comm_data = _json_loads(row.communication, {})
        churn_data = _json_loads(row.churn, {})
        intent_data = _json_loads(row.intent_signals, {})

        for dt_field in ["last_session_at", "first_seen_at", "last_active_at"]:
            if dt_field in engagement_data and engagement_data[dt_field]:
                engagement_data[dt_field] = _parse_datetime(engagement_data[dt_field])

        if "computed_at" in rfm_data and rfm_data["computed_at"]:
            rfm_data["computed_at"] = _parse_datetime(rfm_data["computed_at"])

        if "assessed_at" in churn_data and churn_data["assessed_at"]:
            churn_data["assessed_at"] = _parse_datetime(churn_data["assessed_at"])

        intent_signals = {}
        for key, sig_data in intent_data.items():
            if "detected_at" in sig_data and sig_data["detected_at"]:
                sig_data["detected_at"] = _parse_datetime(sig_data["detected_at"]) or datetime.now(timezone.utc)
            intent_signals[key] = IntentSignal(**sig_data)

        hourly = comm_data.get("hourly_engagement", {})
        if hourly:
            comm_data["hourly_engagement"] = {int(k): v for k, v in hourly.items()}

        return BehavioralProfile(
            id=row.id,
            identity_id=row.identity_id,
            application_id=row.application_id,
            engagement=EngagementProfile(**engagement_data),
            interests=InterestProfile(**interests_data),
            rfm=RFMScore(**rfm_data),
            communication=CommunicationPreference(**comm_data),
            churn=ChurnSignal(**churn_data),
            intent_signals=intent_signals,
            event_counts=_json_loads(row.event_counts, {}),
            traits=_json_loads(row.traits, {}),
            created_at=_parse_datetime(row.created_at) or datetime.now(timezone.utc),
            updated_at=_parse_datetime(row.updated_at) or datetime.now(timezone.utc),
            last_event_at=_parse_datetime(row.last_event_at),
        )


# ======================================================================
# SqlPlatformRepository
# ======================================================================

class SqlPlatformRepository:

    def __init__(self, session_factory):
        self._session_factory = session_factory
        logger.info("SqlPlatformRepository initialized")

    def _session(self) -> Session:
        return self._session_factory()

    def save(self, platform: Platform) -> Platform:
        session = self._session()
        try:
            model = self._to_model(platform)
            session.merge(model)
            session.commit()
            return platform
        finally:
            session.close()

    def get_by_id(self, platform_id: str) -> Optional[Platform]:
        session = self._session()
        try:
            row = session.get(PlatformModel, platform_id)
            return self._from_model(row) if row else None
        finally:
            session.close()

    def get_by_slug(self, slug: str) -> Optional[Platform]:
        session = self._session()
        try:
            row = session.query(PlatformModel).filter_by(slug=slug).first()
            return self._from_model(row) if row else None
        finally:
            session.close()

    def get_by_api_key_hash(self, key_hash: str) -> Optional[Platform]:
        session = self._session()
        try:
            row = session.query(PlatformModel).filter_by(api_key_hash=key_hash).first()
            return self._from_model(row) if row else None
        finally:
            session.close()

    def list_all(self, status: Optional[str] = None) -> List[Platform]:
        session = self._session()
        try:
            q = session.query(PlatformModel)
            if status:
                q = q.filter_by(status=status)
            return [self._from_model(r) for r in q.all()]
        finally:
            session.close()

    def delete(self, platform_id: str) -> bool:
        session = self._session()
        try:
            row = session.get(PlatformModel, platform_id)
            if row:
                session.delete(row)
                session.commit()
                return True
            return False
        finally:
            session.close()

    def _to_model(self, platform: Platform) -> PlatformModel:
        return PlatformModel(
            id=platform.id,
            name=platform.name,
            slug=platform.slug,
            api_key_hash=platform.api_key_hash,
            api_key_prefix=platform.api_key_prefix,
            status=platform.status.value if isinstance(platform.status, PlatformStatus) else platform.status,
            owner_email=platform.owner_email,
            config_yaml=platform.config_yaml,
            quotas=_json_dumps(platform.quotas.model_dump()),
            metadata_=_json_dumps(platform.metadata),
            created_at=platform.created_at,
            updated_at=platform.updated_at,
        )

    def _from_model(self, row: PlatformModel) -> Platform:
        quotas_data = _json_loads(row.quotas, {})
        meta_data = _json_loads(row.metadata_, {})
        return Platform(
            id=row.id,
            name=row.name,
            slug=row.slug,
            api_key_hash=row.api_key_hash,
            api_key_prefix=row.api_key_prefix,
            status=PlatformStatus(row.status),
            owner_email=row.owner_email,
            config_yaml=row.config_yaml,
            quotas=PlatformQuotas(**quotas_data),
            metadata=meta_data,
            created_at=_parse_datetime(row.created_at) or datetime.now(timezone.utc),
            updated_at=_parse_datetime(row.updated_at) or datetime.now(timezone.utc),
        )
