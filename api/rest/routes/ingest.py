"""
Universal Webhook Receiver.

Accepts raw webhooks from external services (Stripe, Paystack, Shopify, …),
transforms them via per-source InboundTransformers, and feeds the resulting
events through the standard UGIE pipeline.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from api.rest.app import pipeline
from api.rest.middleware import require_platform
from api.rest.routes.events import _build_event, _process_event, EventRequest
from core.platform.schema import Platform

router = APIRouter(tags=["ingest"])


@router.get("/ingest/sources")
def list_sources():
    registry = pipeline.ingest_registry
    if registry is None:
        return {"sources": []}
    return {"sources": registry.list_sources()}


@router.post("/ingest/{source}")
async def ingest_webhook(
    source: str,
    request: Request,
    platform: Platform = Depends(require_platform),
):
    registry = pipeline.ingest_registry
    if registry is None:
        raise HTTPException(status_code=500, detail="Ingest registry not initialized")

    transformer = registry.get(source)
    if transformer is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown ingest source: {source}. Available: {registry.list_sources()}",
        )

    body: Dict[str, Any] = await request.json()
    headers = dict(request.headers)

    try:
        event_dicts = transformer.transform(body, platform.id, headers=headers)
    except Exception as e:
        raise HTTPException(
            status_code=422,
            detail=f"Transformer error for source '{source}': {e}",
        )

    results = []
    for ev_dict in event_dicts:
        ev_dict["application_id"] = platform.id
        req = EventRequest(**ev_dict)
        event = _build_event(req)
        results.append(_process_event(event))

    return {
        "source": source,
        "events_created": len(results),
        "results": results,
    }
