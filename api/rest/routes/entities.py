"""Entity CRUD endpoints."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core.entity.schema import Entity, EntityType, EntityStatus
from core.platform.schema import Platform
from api.rest.app import pipeline
from api.rest.middleware import get_current_platform

router = APIRouter(tags=["entities"])


class EntityCreateRequest(BaseModel):
    application_id: str
    type_name: str
    type: str = "Custom"
    status: str = "active"
    state: Optional[str] = None
    identity_id: Optional[str] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)


@router.post("/entities")
def create_entity(
    req: EntityCreateRequest,
    platform: Optional[Platform] = Depends(get_current_platform),
):
    try:
        entity_type = EntityType(req.type)
    except ValueError:
        entity_type = EntityType.CUSTOM

    try:
        status = EntityStatus(req.status)
    except ValueError:
        status = EntityStatus.ACTIVE

    app_id = platform.id if platform else req.application_id
    entity = Entity(
        application_id=app_id,
        type=entity_type,
        type_name=req.type_name,
        status=status,
        state=req.state,
        identity_id=req.identity_id,
        attributes=req.attributes,
        tags=req.tags,
    )
    pipeline.entity_repo.save(entity)
    return entity.model_dump()


@router.get("/entities/{entity_id}")
def get_entity(
    entity_id: str,
    platform: Optional[Platform] = Depends(get_current_platform),
):
    entity = pipeline.entity_repo.get(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    if platform and entity.application_id != platform.id:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity.model_dump()


@router.get("/entities")
def list_entities(
    application_id: Optional[str] = Query(None),
    type_name: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    platform: Optional[Platform] = Depends(get_current_platform),
):
    app_id = platform.id if platform else application_id
    if app_id and type_name:
        entity_status = None
        if status:
            try:
                entity_status = EntityStatus(status)
            except ValueError:
                pass
        entities = pipeline.entity_repo.find_by_application_and_type(
            app_id, type_name, entity_status
        )
    else:
        entities = []
    return [e.model_dump() for e in entities]


@router.delete("/entities/{entity_id}")
def delete_entity(
    entity_id: str,
    platform: Optional[Platform] = Depends(get_current_platform),
):
    if platform:
        entity = pipeline.entity_repo.get(entity_id)
        if not entity or entity.application_id != platform.id:
            raise HTTPException(status_code=404, detail="Entity not found")
    entity = pipeline.entity_repo.soft_delete(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Entity not found")
    return {"status": "deleted", "entity_id": entity_id}
