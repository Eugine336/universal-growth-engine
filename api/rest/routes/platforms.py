"""Platform management endpoints."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.rest.app import pipeline
from api.rest.middleware import require_platform
from core.platform.schema import Platform, PlatformQuotas

router = APIRouter(tags=["platforms"])


class PlatformCreateRequest(BaseModel):
    name: str
    slug: str
    owner_email: str
    max_events_per_hour: int = 10000
    max_entities: int = 100000
    max_decisions_per_hour: int = 5000


class PlatformUpdateRequest(BaseModel):
    name: Optional[str] = None
    owner_email: Optional[str] = None
    max_events_per_hour: Optional[int] = None
    max_entities: Optional[int] = None
    max_decisions_per_hour: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None


class PlatformConfigRequest(BaseModel):
    yaml_content: str


def _platform_response(platform: Platform) -> dict:
    return {
        "id": platform.id,
        "name": platform.name,
        "slug": platform.slug,
        "status": platform.status.value,
        "owner_email": platform.owner_email,
        "api_key_prefix": platform.api_key_prefix,
        "quotas": platform.quotas.model_dump(),
        "metadata": platform.metadata,
        "has_config": platform.config_yaml is not None,
        "created_at": platform.created_at.isoformat(),
        "updated_at": platform.updated_at.isoformat(),
    }


@router.post("/platforms")
def register_platform(req: PlatformCreateRequest):
    registry = pipeline.platform_registry
    if registry is None:
        raise HTTPException(status_code=500, detail="Platform registry not initialized")
    quotas = PlatformQuotas(
        max_events_per_hour=req.max_events_per_hour,
        max_entities=req.max_entities,
        max_decisions_per_hour=req.max_decisions_per_hour,
    )
    try:
        platform, raw_key = registry.register(
            name=req.name,
            slug=req.slug,
            owner_email=req.owner_email,
            quotas=quotas,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    resp = _platform_response(platform)
    resp["api_key"] = raw_key
    return resp


@router.get("/platforms/me")
def get_my_platform(platform: Platform = Depends(require_platform)):
    return _platform_response(platform)


@router.put("/platforms/me")
def update_my_platform(
    req: PlatformUpdateRequest,
    platform: Platform = Depends(require_platform),
):
    registry = pipeline.platform_registry
    kwargs: Dict[str, Any] = {}
    if req.name is not None:
        kwargs["name"] = req.name
    if req.owner_email is not None:
        kwargs["owner_email"] = req.owner_email
    if req.metadata is not None:
        kwargs["metadata"] = req.metadata

    if req.max_events_per_hour is not None or req.max_entities is not None or req.max_decisions_per_hour is not None:
        q = platform.quotas.model_dump()
        if req.max_events_per_hour is not None:
            q["max_events_per_hour"] = req.max_events_per_hour
        if req.max_entities is not None:
            q["max_entities"] = req.max_entities
        if req.max_decisions_per_hour is not None:
            q["max_decisions_per_hour"] = req.max_decisions_per_hour
        kwargs["quotas"] = PlatformQuotas(**q)

    updated = registry.update(platform.id, **kwargs)
    if not updated:
        raise HTTPException(status_code=404, detail="Platform not found")
    return _platform_response(updated)


@router.post("/platforms/me/config")
def upload_config(
    req: PlatformConfigRequest,
    platform: Platform = Depends(require_platform),
):
    from core.config.schema import ApplicationConfig
    import yaml

    try:
        data = yaml.safe_load(req.yaml_content)
        config = ApplicationConfig.model_validate(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid config: {e}")

    if pipeline.config_loader:
        loader = pipeline.config_loader
        loader._register_entities(config)
        loader._register_state_machines(config)
        loader._register_event_policy(config)
        loader._register_policies(config)
        loader._register_connectors(config)

    registry = pipeline.platform_registry
    registry.update(platform.id, config_yaml=req.yaml_content)
    return {
        "status": "loaded",
        "application_id": config.application.id,
        "entities": len(config.entities),
        "policies": len(config.policies),
        "state_machines": len(config.state_machines),
        "connectors": len(config.connectors),
    }


@router.post("/platforms/me/rotate-key")
def rotate_key(platform: Platform = Depends(require_platform)):
    registry = pipeline.platform_registry
    result = registry.rotate_api_key(platform.id)
    if not result:
        raise HTTPException(status_code=404, detail="Platform not found")
    updated, new_key = result
    resp = _platform_response(updated)
    resp["api_key"] = new_key
    return resp


@router.get("/platforms/me/stats")
def platform_stats(platform: Platform = Depends(require_platform)):
    stats: Dict[str, Any] = {"platform_id": platform.id, "slug": platform.slug}
    if pipeline.entity_repo:
        stats["entities"] = pipeline.entity_repo.count(application_id=platform.id)
    if pipeline.behavior_repo:
        stats["profiles"] = pipeline.behavior_repo.stats(application_id=platform.id)
    return stats
