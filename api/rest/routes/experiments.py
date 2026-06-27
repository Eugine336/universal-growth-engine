"""Experiment endpoints."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.rest.app import pipeline

router = APIRouter(tags=["experiments"])


class VariantCreate(BaseModel):
    id: str
    name: str
    weight: float = 0.5
    policy_overrides: Dict[str, Any] = Field(default_factory=dict)


class ExperimentCreate(BaseModel):
    application_id: str
    name: str
    description: str = ""
    target_policy_id: str
    variants: List[VariantCreate]
    target_rfm_segments: List[str] = Field(default_factory=list)
    target_engagement_tiers: List[str] = Field(default_factory=list)


class ExperimentUpdate(BaseModel):
    action: str  # start | pause | complete


class ConversionRequest(BaseModel):
    identity_id: str


@router.post("/experiments")
def create_experiment(req: ExperimentCreate):
    from core.experimentation.schema import Experiment, ExperimentVariant

    variants = [
        ExperimentVariant(
            id=v.id,
            name=v.name,
            weight=v.weight,
            policy_overrides=v.policy_overrides,
        )
        for v in req.variants
    ]
    experiment = Experiment(
        application_id=req.application_id,
        name=req.name,
        description=req.description,
        target_policy_id=req.target_policy_id,
        variants=variants,
        target_rfm_segments=req.target_rfm_segments,
        target_engagement_tiers=req.target_engagement_tiers,
    )
    pipeline.experimentation_engine.register(experiment)
    return experiment.model_dump()


@router.get("/experiments")
def list_experiments(
    application_id: Optional[str] = None,
    status: Optional[str] = None,
):
    from core.experimentation.schema import ExperimentStatus

    status_enum = None
    if status:
        try:
            status_enum = ExperimentStatus(status)
        except ValueError:
            raise HTTPException(400, f"Invalid status: {status}")

    experiments = pipeline.experimentation_engine.list_experiments(
        application_id=application_id,
        status=status_enum,
    )
    return [e.model_dump() for e in experiments]


@router.get("/experiments/{experiment_id}")
def get_experiment(experiment_id: str):
    exp = pipeline.experimentation_engine.get(experiment_id)
    if not exp:
        raise HTTPException(404, "Experiment not found")
    results = pipeline.experimentation_engine.get_results(experiment_id)
    data = exp.model_dump()
    data["results"] = results
    return data


@router.patch("/experiments/{experiment_id}")
def update_experiment(experiment_id: str, req: ExperimentUpdate):
    action_map = {
        "start": pipeline.experimentation_engine.start,
        "pause": pipeline.experimentation_engine.pause,
        "complete": pipeline.experimentation_engine.complete,
    }
    fn = action_map.get(req.action)
    if not fn:
        raise HTTPException(400, f"Invalid action: {req.action}")
    exp = fn(experiment_id)
    if not exp:
        raise HTTPException(404, "Experiment not found")
    return exp.model_dump()


@router.post("/experiments/{experiment_id}/convert")
def record_conversion(experiment_id: str, req: ConversionRequest):
    ok = pipeline.experimentation_engine.record_conversion(
        experiment_id, req.identity_id,
    )
    if not ok:
        raise HTTPException(404, "No assignment found for this identity/experiment")
    return {"recorded": True}
