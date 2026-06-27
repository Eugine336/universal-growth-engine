"""Budget allocation endpoints."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.rest.app import pipeline

router = APIRouter(tags=["budget"])


class ChannelConfigCreate(BaseModel):
    auto_pause_threshold: float = 0.0
    min_budget: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PlanCreate(BaseModel):
    total_budget: float
    period: str = "monthly"
    channel_allocations: Dict[str, float] = Field(default_factory=dict)
    auto_optimize: bool = True
    optimization_frequency: str = "daily"
    reallocation_strategy: str = "proportional"
    channel_configs: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class PlanUpdate(BaseModel):
    total_budget: Optional[float] = None
    period: Optional[str] = None
    auto_optimize: Optional[bool] = None
    optimization_frequency: Optional[str] = None
    reallocation_strategy: Optional[str] = None
    status: Optional[str] = None


class RecordActionRequest(BaseModel):
    channel: str
    cost: float = 0.0
    success: bool = True


class RecordConversionRequest(BaseModel):
    channel: str


@router.post("/budget/plans")
def create_plan(
    req: PlanCreate,
    platform_id: Optional[str] = "default",
):
    plan = pipeline.budget_allocator.create_plan(
        platform_id=platform_id,
        total_budget=req.total_budget,
        period=req.period,
        channel_allocations=req.channel_allocations,
        auto_optimize=req.auto_optimize,
        optimization_frequency=req.optimization_frequency,
        reallocation_strategy=req.reallocation_strategy,
        channel_configs=req.channel_configs,
    )
    return plan.model_dump()


@router.get("/budget/plans")
def get_plan(platform_id: Optional[str] = "default"):
    plan = pipeline.budget_allocator.get_plan(platform_id)
    if not plan:
        raise HTTPException(404, "No budget plan found for this platform")
    return plan.model_dump()


@router.put("/budget/plans")
def update_plan(
    req: PlanUpdate,
    platform_id: Optional[str] = "default",
):
    plan = pipeline.budget_allocator.update_plan(
        platform_id=platform_id,
        total_budget=req.total_budget,
        period=req.period,
        auto_optimize=req.auto_optimize,
        optimization_frequency=req.optimization_frequency,
        reallocation_strategy=req.reallocation_strategy,
        status=req.status,
    )
    if not plan:
        raise HTTPException(404, "No budget plan found for this platform")
    return plan.model_dump()


@router.get("/budget/performance")
def get_performance(platform_id: Optional[str] = "default"):
    perf = pipeline.budget_allocator.get_performance(platform_id)
    return {ch: p.model_dump() for ch, p in perf.items()}


@router.get("/budget/performance/{channel}")
def get_channel_performance(channel: str, platform_id: Optional[str] = "default"):
    perf = pipeline.budget_allocator.get_channel_performance(platform_id, channel)
    if not perf:
        raise HTTPException(404, f"No performance data for channel: {channel}")
    return perf.model_dump()


@router.post("/budget/optimize")
def optimize(platform_id: Optional[str] = "default"):
    event = pipeline.budget_allocator.optimize(platform_id)
    if not event:
        return {"status": "no_changes", "reason": "No reallocation needed"}
    return event.model_dump()


@router.get("/budget/recommendation")
def get_recommendation(platform_id: Optional[str] = "default"):
    return pipeline.budget_allocator.get_recommendation(platform_id)


@router.get("/budget/history")
def get_history(platform_id: Optional[str] = "default"):
    events = pipeline.budget_allocator.get_reallocation_history(platform_id)
    return [e.model_dump() for e in events]


@router.post("/budget/channels/{channel}/pause")
def pause_channel(channel: str, platform_id: Optional[str] = "default"):
    plan = pipeline.budget_allocator.pause_channel(platform_id, channel)
    if not plan:
        raise HTTPException(404, "Plan or channel not found")
    return plan.model_dump()


@router.post("/budget/channels/{channel}/resume")
def resume_channel(channel: str, platform_id: Optional[str] = "default"):
    plan = pipeline.budget_allocator.resume_channel(platform_id, channel)
    if not plan:
        raise HTTPException(404, "Plan or channel not found")
    return plan.model_dump()


@router.get("/budget/stats")
def get_stats():
    return pipeline.budget_allocator.stats()
