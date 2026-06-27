"""Cross-platform identity endpoints."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.platform.schema import Platform
from api.rest.app import pipeline
from api.rest.middleware import get_current_platform

router = APIRouter(tags=["cross-platform"])


class ConfigRequest(BaseModel):
    platform_id: Optional[str] = None
    allow_cross_platform_linking: bool = False
    share_behavioral_data: bool = False
    allowed_partner_platforms: List[str] = Field(default_factory=list)
    linkable_touchpoint_types: List[str] = Field(
        default_factory=lambda: ["email", "phone"]
    )


@router.post("/cross-platform/config")
def set_config(
    req: ConfigRequest,
    platform: Optional[Platform] = Depends(get_current_platform),
):
    from core.identity.cross_platform import CrossPlatformConfig

    pid = req.platform_id or (platform.id if platform else None)
    if not pid:
        raise HTTPException(400, "platform_id required")

    config = CrossPlatformConfig(
        platform_id=pid,
        allow_cross_platform_linking=req.allow_cross_platform_linking,
        share_behavioral_data=req.share_behavioral_data,
        allowed_partner_platforms=req.allowed_partner_platforms,
        linkable_touchpoint_types=req.linkable_touchpoint_types,
    )
    result = pipeline.cross_platform_manager.set_platform_config(config)
    return result.model_dump()


@router.get("/cross-platform/config")
def get_config(
    platform_id: Optional[str] = None,
    platform: Optional[Platform] = Depends(get_current_platform),
):
    pid = platform_id or (platform.id if platform else None)
    if not pid:
        raise HTTPException(400, "platform_id required")

    config = pipeline.cross_platform_manager.get_platform_config(pid)
    if not config:
        raise HTTPException(404, "No cross-platform config found")
    return config.model_dump()


@router.get("/cross-platform/identities")
def list_cross_platform_identities(
    platform_id: Optional[str] = None,
    platform: Optional[Platform] = Depends(get_current_platform),
):
    pid = platform_id or (platform.id if platform else None)
    if not pid:
        raise HTTPException(400, "platform_id required")
    return pipeline.cross_platform_manager.find_cross_platform_identities(pid)


@router.get("/cross-platform/identities/{identity_id}/profile")
def get_cross_platform_profile(
    identity_id: str,
    platform_id: Optional[str] = None,
    platform: Optional[Platform] = Depends(get_current_platform),
):
    pid = platform_id or (platform.id if platform else None)
    if not pid:
        raise HTTPException(400, "platform_id required")

    profile = pipeline.cross_platform_manager.get_cross_platform_profile(
        identity_id, pid
    )
    if not profile:
        raise HTTPException(404, "No cross-platform profile available")
    return profile


@router.get("/cross-platform/shared/{other_platform_id}")
def get_shared_identities(
    other_platform_id: str,
    platform_id: Optional[str] = None,
    platform: Optional[Platform] = Depends(get_current_platform),
):
    pid = platform_id or (platform.id if platform else None)
    if not pid:
        raise HTTPException(400, "platform_id required")

    identities = pipeline.cross_platform_manager.get_shared_identities(
        pid, other_platform_id
    )
    return [
        {
            "identity_id": i.id,
            "canonical_email": i.canonical_email,
            "platforms": i.application_ids,
        }
        for i in identities
    ]


@router.get("/cross-platform/promotion-candidates/{target_platform_id}")
def get_promotion_candidates(
    target_platform_id: str,
    platform_id: Optional[str] = None,
    min_engagement_tier: str = "warming",
    platform: Optional[Platform] = Depends(get_current_platform),
):
    pid = platform_id or (platform.id if platform else None)
    if not pid:
        raise HTTPException(400, "platform_id required")

    return pipeline.cross_platform_manager.get_cross_promotion_candidates(
        source_platform_id=pid,
        target_platform_id=target_platform_id,
        min_engagement_tier=min_engagement_tier,
    )


@router.get("/cross-platform/stats")
def get_stats():
    return pipeline.cross_platform_manager.stats()
