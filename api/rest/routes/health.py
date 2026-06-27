"""Health and stats endpoints."""

from fastapi import APIRouter

from api.rest.app import pipeline

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    return {"status": "ok", "version": "0.1.0"}


@router.get("/stats")
def stats():
    data = {}
    if pipeline.event_bus:
        data["event_bus"] = pipeline.event_bus.stats()
    if pipeline.decision_engine:
        data["decision_engine"] = pipeline.decision_engine.stats()
    if pipeline.action_orchestrator:
        data["action_orchestrator"] = pipeline.action_orchestrator.stats()
    if pipeline.entity_repo:
        data["entities"] = pipeline.entity_repo.stats()
    if pipeline.identity_graph:
        data["identities"] = pipeline.identity_graph.stats()
    if pipeline.behavior_repo:
        data["behavior"] = pipeline.behavior_repo.stats()
    return data
