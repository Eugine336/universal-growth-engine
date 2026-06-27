"""Admin endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.rest.app import pipeline

router = APIRouter(tags=["admin"])


def _manager():
    from core.admin.manager import AdminManager

    return AdminManager(pipeline)


class PlatformUpdateRequest(BaseModel):
    name: str = None
    metadata: dict = None


@router.get("/admin/health")
def system_health():
    return _manager().get_system_health().model_dump()


@router.get("/admin/platforms")
def list_platforms():
    return _manager().list_platforms_summary()


@router.get("/admin/platforms/{platform_id}")
def get_platform(platform_id: str):
    detail = _manager().get_platform_detail(platform_id)
    if not detail:
        raise HTTPException(404, "Platform not found")
    return detail


@router.put("/admin/platforms/{platform_id}")
def update_platform(platform_id: str, req: PlatformUpdateRequest):
    from core.admin.schema import PlatformConfigUpdate

    updates = PlatformConfigUpdate(name=req.name, metadata=req.metadata)
    result = _manager().update_platform_config(platform_id, updates)
    if not result:
        raise HTTPException(404, "Platform not found")
    return result


@router.get("/admin/stats")
def global_stats():
    return _manager().get_event_bus_stats()
