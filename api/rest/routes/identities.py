"""Identity lookup endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from core.platform.schema import Platform
from api.rest.app import pipeline
from api.rest.middleware import get_current_platform

router = APIRouter(tags=["identities"])


@router.get("/identities/{identity_id}")
def get_identity(
    identity_id: str,
    platform: Optional[Platform] = Depends(get_current_platform),
):
    identity = pipeline.identity_graph.get(identity_id)
    if not identity:
        raise HTTPException(status_code=404, detail="Identity not found")
    if platform and platform.id not in identity.application_ids:
        raise HTTPException(status_code=404, detail="Identity not found")
    return identity.model_dump()


@router.get("/identities/by-email/{email}")
def get_identity_by_email(
    email: str,
    platform: Optional[Platform] = Depends(get_current_platform),
):
    identity = pipeline.identity_graph.find_by_email(email)
    if not identity:
        raise HTTPException(status_code=404, detail="Identity not found for email")
    if platform and platform.id not in identity.application_ids:
        raise HTTPException(status_code=404, detail="Identity not found for email")
    return identity.model_dump()


@router.get("/identities/{identity_id}/profile")
def get_profile(
    identity_id: str,
    platform: Optional[Platform] = Depends(get_current_platform),
):
    identity = pipeline.identity_graph.get(identity_id)
    if not identity:
        raise HTTPException(status_code=404, detail="Identity not found")
    if platform and platform.id not in identity.application_ids:
        raise HTTPException(status_code=404, detail="Identity not found")

    app_id = platform.id if platform else (identity.application_ids[0] if identity.application_ids else None)
    if not app_id:
        raise HTTPException(status_code=404, detail="No application data for identity")
    profile = pipeline.behavior_repo.get(identity_id, app_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Behavioral profile not found")
    return profile.model_dump()
