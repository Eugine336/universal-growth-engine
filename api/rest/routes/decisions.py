"""Decision endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.rest.app import pipeline

router = APIRouter(tags=["decisions"])


class DecideRequest(BaseModel):
    identity_id: str
    application_id: str
    trigger_event_type: Optional[str] = None


@router.post("/decide")
def decide(req: DecideRequest):
    decisions = pipeline.decision_engine.decide(
        identity_id=req.identity_id,
        application_id=req.application_id,
        trigger_event_type=req.trigger_event_type,
        return_all=True,
    )
    if not decisions:
        return {"decisions": [], "message": "No matching policies"}
    return {"decisions": [d.model_dump() for d in decisions]}


@router.get("/decisions/{identity_id}")
def get_decisions(identity_id: str, application_id: Optional[str] = None):
    history = pipeline.decision_engine.get_history(
        identity_id=identity_id,
        application_id=application_id,
    )
    return [d.model_dump() for d in history]
