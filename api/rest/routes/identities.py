"""Identity lookup endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.rest.app import pipeline

router = APIRouter(tags=["identities"])


@router.get("/identities/{identity_id}")
def get_identity(identity_id: str):
    identity = pipeline.identity_graph.get(identity_id)
    if not identity:
        raise HTTPException(status_code=404, detail="Identity not found")
    return identity.model_dump()


@router.get("/identities/by-email/{email}")
def get_identity_by_email(email: str):
    identity = pipeline.identity_graph.find_by_email(email)
    if not identity:
        raise HTTPException(status_code=404, detail="Identity not found for email")
    return identity.model_dump()


@router.get("/identities/{identity_id}/profile")
def get_profile(identity_id: str):
    identity = pipeline.identity_graph.get(identity_id)
    if not identity:
        raise HTTPException(status_code=404, detail="Identity not found")
    if not identity.application_ids:
        raise HTTPException(status_code=404, detail="No application data for identity")
    app_id = identity.application_ids[0]
    profile = pipeline.behavior_repo.get(identity_id, app_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Behavioral profile not found")
    return profile.model_dump()
