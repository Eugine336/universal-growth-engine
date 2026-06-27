"""Audience endpoints."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.rest.app import pipeline

router = APIRouter(tags=["audiences"])


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------

class RuleCreate(BaseModel):
    field: str
    operator: str
    value: Any = None


class RuleGroupCreate(BaseModel):
    operator: str = "AND"
    rules: List[RuleCreate] = Field(default_factory=list)


class AudienceCreate(BaseModel):
    name: str
    description: str = ""
    groups: List[RuleGroupCreate] = Field(default_factory=list)


class AudienceUpdate(BaseModel):
    name: str
    description: str = ""
    groups: List[RuleGroupCreate] = Field(default_factory=list)


class ExportRequest(BaseModel):
    destination: str  # meta | google | tiktok | linkedin
    config: Dict[str, Any] = Field(default_factory=dict)


class PreviewRequest(BaseModel):
    name: str = "preview"
    description: str = ""
    groups: List[RuleGroupCreate] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/audiences")
def create_audience(
    req: AudienceCreate,
    platform_id: Optional[str] = "default",
):
    from core.audience.schema import (
        AudienceDefinition,
        AudienceRule,
        AudienceRuleGroup,
    )

    definition = AudienceDefinition(
        name=req.name,
        description=req.description,
        groups=[
            AudienceRuleGroup(
                operator=g.operator,
                rules=[
                    AudienceRule(field=r.field, operator=r.operator, value=r.value)
                    for r in g.rules
                ],
            )
            for g in req.groups
        ],
    )
    audience = pipeline.audience_engine.create_audience(platform_id, definition)
    return audience.model_dump()


@router.get("/audiences")
def list_audiences(platform_id: Optional[str] = "default"):
    audiences = pipeline.audience_engine.list_audiences(platform_id)
    return [a.model_dump() for a in audiences]


@router.get("/audiences/{audience_id}")
def get_audience(audience_id: str):
    audience = pipeline.audience_engine.get_audience(audience_id)
    if not audience:
        raise HTTPException(404, "Audience not found")
    return audience.model_dump()


@router.put("/audiences/{audience_id}")
def update_audience(audience_id: str, req: AudienceUpdate):
    from core.audience.schema import (
        AudienceDefinition,
        AudienceRule,
        AudienceRuleGroup,
    )

    definition = AudienceDefinition(
        name=req.name,
        description=req.description,
        groups=[
            AudienceRuleGroup(
                operator=g.operator,
                rules=[
                    AudienceRule(field=r.field, operator=r.operator, value=r.value)
                    for r in g.rules
                ],
            )
            for g in req.groups
        ],
    )
    audience = pipeline.audience_engine.update_audience(audience_id, definition)
    if not audience:
        raise HTTPException(404, "Audience not found")
    return audience.model_dump()


@router.post("/audiences/{audience_id}/evaluate")
def evaluate_audience(audience_id: str):
    audience = pipeline.audience_engine.get_audience(audience_id)
    if not audience:
        raise HTTPException(404, "Audience not found")
    profiles = pipeline.audience_engine.evaluate(audience_id)
    return {
        "audience_id": audience_id,
        "matching_count": len(profiles),
        "identity_ids": [p.identity_id for p in profiles],
    }


@router.post("/audiences/preview")
def preview_audience(
    req: PreviewRequest,
    platform_id: Optional[str] = "default",
):
    from core.audience.schema import (
        AudienceDefinition,
        AudienceRule,
        AudienceRuleGroup,
    )

    definition = AudienceDefinition(
        name=req.name,
        description=req.description,
        groups=[
            AudienceRuleGroup(
                operator=g.operator,
                rules=[
                    AudienceRule(field=r.field, operator=r.operator, value=r.value)
                    for r in g.rules
                ],
            )
            for g in req.groups
        ],
    )
    result = pipeline.audience_engine.preview(platform_id, definition)
    return result


@router.post("/audiences/{audience_id}/export")
def export_audience(audience_id: str, req: ExportRequest):
    from core.audience.schema import ExportDestination

    audience = pipeline.audience_engine.get_audience(audience_id)
    if not audience:
        raise HTTPException(404, "Audience not found")

    try:
        destination = ExportDestination(req.destination)
    except ValueError:
        raise HTTPException(
            400,
            f"Invalid destination: {req.destination}. "
            f"Must be one of: meta, google, tiktok, linkedin",
        )

    job = pipeline.audience_exporter.export(
        audience_id=audience_id,
        destination=destination,
        config=req.config,
    )
    return job.model_dump()


@router.get("/audiences/exports/{job_id}")
def get_export_job(job_id: str):
    job = pipeline.audience_exporter.get_job(job_id)
    if not job:
        raise HTTPException(404, "Export job not found")
    return job.model_dump()


@router.post("/audiences/{audience_id}/archive")
def archive_audience(audience_id: str):
    audience = pipeline.audience_engine.archive_audience(audience_id)
    if not audience:
        raise HTTPException(404, "Audience not found")
    return audience.model_dump()
