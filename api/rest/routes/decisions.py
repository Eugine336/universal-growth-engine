"""Decision endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from core.platform.schema import Platform
from api.rest.app import pipeline
from api.rest.middleware import get_current_platform

router = APIRouter(tags=["decisions"])


class DecideRequest(BaseModel):
    identity_id: str
    application_id: str = ""
    trigger_event_type: Optional[str] = None


@router.post("/decide")
def decide(
    req: DecideRequest,
    platform: Optional[Platform] = Depends(get_current_platform),
):
    app_id = platform.id if platform else req.application_id
    decisions = pipeline.decision_engine.decide(
        identity_id=req.identity_id,
        application_id=app_id,
        trigger_event_type=req.trigger_event_type,
        return_all=True,
    )
    if not decisions:
        return {"decisions": [], "message": "No matching policies"}
    return {"decisions": [d.model_dump() for d in decisions]}


@router.get("/decisions/{identity_id}")
def get_decisions(
    identity_id: str,
    application_id: Optional[str] = None,
    platform: Optional[Platform] = Depends(get_current_platform),
):
    app_id = platform.id if platform else application_id
    history = pipeline.decision_engine.get_history(
        identity_id=identity_id,
        application_id=app_id,
    )
    return [d.model_dump() for d in history]
