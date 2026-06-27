"""Event ingestion endpoints."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.events.schema import Event, EventType, EventSource, EventContext, DeviceContext, GeoContext
from api.rest.app import pipeline

router = APIRouter(tags=["events"])


class EventRequest(BaseModel):
    application_id: str
    type: str
    custom_type: Optional[str] = None
    actor_id: Optional[str] = None
    actor_type: Optional[str] = None
    target_id: Optional[str] = None
    target_type: Optional[str] = None
    properties: Dict[str, Any] = Field(default_factory=dict)
    source: str = "api"
    context: Optional[Dict[str, Any]] = None


def _build_event(req: EventRequest) -> Event:
    try:
        event_type = EventType(req.type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown event type: {req.type}")

    ctx = EventContext()
    if req.context:
        device_data = req.context.get("device")
        geo_data = req.context.get("geo")
        ctx = EventContext(
            session_id=req.context.get("session_id"),
            device=DeviceContext(**device_data) if device_data else None,
            geo=GeoContext(**geo_data) if geo_data else None,
            referrer=req.context.get("referrer"),
            utm_source=req.context.get("utm_source"),
            utm_medium=req.context.get("utm_medium"),
            utm_campaign=req.context.get("utm_campaign"),
            utm_content=req.context.get("utm_content"),
            utm_term=req.context.get("utm_term"),
            experiment_id=req.context.get("experiment_id"),
            variant_id=req.context.get("variant_id"),
        )

    try:
        source = EventSource(req.source)
    except ValueError:
        source = EventSource.API

    return Event(
        application_id=req.application_id,
        type=event_type,
        custom_type=req.custom_type,
        actor_id=req.actor_id,
        actor_type=req.actor_type,
        target_id=req.target_id,
        target_type=req.target_type,
        properties=req.properties,
        source=source,
        context=ctx,
    )


def _process_event(event: Event) -> Dict[str, Any]:
    result = pipeline.event_bus.submit(event)

    if result.success and event.actor_id:
        resolution = pipeline.identity_resolver.resolve_from_event(event)
        if resolution:
            profile = pipeline.behavior_repo.get_or_create(
                identity_id=resolution.identity.id,
                application_id=event.application_id,
            )
            pipeline.behavior_builder.apply(event, profile)
            pipeline.behavior_repo.save(profile)

    return result.to_dict()


@router.post("/events")
def submit_event(req: EventRequest):
    event = _build_event(req)
    return _process_event(event)


@router.post("/events/batch")
def submit_batch(events: List[EventRequest]):
    results = []
    for req in events:
        event = _build_event(req)
        results.append(_process_event(event))
    return results
