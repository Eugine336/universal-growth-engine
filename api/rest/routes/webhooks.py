"""Webhook callback endpoints for receiving action feedback from external systems."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.rest.app import pipeline

router = APIRouter(tags=["webhooks"])


class ActionFeedbackRequest(BaseModel):
    action_id: str
    event: str
    data: Dict[str, Any] = Field(default_factory=dict)


@router.post("/webhooks/action-feedback")
def action_feedback(req: ActionFeedbackRequest):
    if not pipeline.action_orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")

    action = pipeline.action_orchestrator.record_feedback(
        action_id=req.action_id,
        event=req.event,
        data=req.data,
    )
    if not action:
        raise HTTPException(status_code=404, detail=f"Action '{req.action_id}' not found")

    return {
        "action_id": action.id,
        "event": req.event,
        "status": action.status.value,
        "feedback": action.feedback,
    }
