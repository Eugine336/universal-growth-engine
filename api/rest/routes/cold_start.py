"""Cold Start & Acquisition Plan endpoints."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

from api.rest.app import pipeline

router = APIRouter(tags=["cold-start"])


def _category_response(cat) -> dict:
    return {
        "category_id": cat.category_id,
        "confidence": cat.confidence,
        "matched_signals": cat.matched_signals,
        "fallback": cat.fallback,
    }


def _playbook_response(playbook) -> dict:
    return {
        "platform_id": playbook.platform_id,
        "stage": playbook.stage,
        "generated_at": playbook.generated_at.isoformat(),
        "category": _category_response(playbook.category),
        "value_proposition": playbook.value_proposition,
        "activation_bottleneck": playbook.activation_bottleneck,
        "first_value_moment": playbook.first_value_moment,
        "estimated_cac": playbook.estimated_cac,
        "cold_start_window_days": playbook.cold_start_window_days,
        "budget_split": playbook.budget_split,
        "success_metrics": playbook.success_metrics,
        "target_archetypes": [
            {"name": a.name, "description": a.description, "age_range": a.age_range, "channels": a.channels, "message_tone": a.message_tone}
            for a in playbook.target_archetypes
        ],
        "acquisition_channels": [
            {"channel": c.channel, "priority": c.priority, "rationale": c.rationale, "budget_pct": c.recommended_budget_pct}
            for c in playbook.acquisition_channels
        ],
        "activation_sequence": [
            {"day": s.day, "trigger": s.trigger, "action_type": s.action_type, "goal": s.goal}
            for s in playbook.activation_sequence
        ],
        "policies_count": len(playbook.recommended_policies),
    }


def _plan_response(plan) -> dict:
    return {
        "id": plan.id,
        "platform_id": plan.platform_id,
        "stage": plan.stage,
        "generated_at": plan.generated_at.isoformat(),
        "estimated_cac": plan.estimated_cac,
        "total_recommended_budget": plan.total_recommended_budget,
        "channel_plans": [
            {
                "channel": cp.channel,
                "priority": cp.priority,
                "budget_pct": cp.recommended_budget_pct,
                "expected_cac_range": cp.expected_cac_range,
                "rationale": cp.rationale,
                "targeting": {
                    "name": cp.targeting.name,
                    "age_min": cp.targeting.age_min,
                    "age_max": cp.targeting.age_max,
                    "interests": cp.targeting.interests,
                    "platforms": cp.targeting.platforms,
                    "source": cp.targeting.source,
                },
                "creative": {
                    "format": cp.creative.format,
                    "headline": cp.creative.headline,
                    "cta": cp.creative.cta,
                    "tone": cp.creative.tone,
                },
            }
            for cp in plan.channel_plans
        ],
        "lookalike_seeds": [
            {
                "source_audience": ls.source_audience,
                "platform": ls.platform,
                "similarity_pct": ls.similarity_pct,
                "seed_count": len(ls.seed_identity_ids),
            }
            for ls in plan.lookalike_seeds
        ],
    }


@router.get("/platforms/{platform_id}/cold-start")
def get_cold_start(platform_id: str):
    engine = pipeline.cold_start_engine
    if engine is None:
        raise HTTPException(status_code=500, detail="Cold start engine not initialized")
    result = engine.get_result(platform_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No cold start result for this platform")
    return {
        "platform_id": result.platform_id,
        "category": _category_response(result.category),
        "policies_registered": result.policies_registered,
        "ran_at": result.ran_at.isoformat(),
        "playbook": _playbook_response(result.playbook),
    }


@router.get("/platforms/{platform_id}/playbook")
def get_playbook(platform_id: str):
    engine = pipeline.cold_start_engine
    if engine is None:
        raise HTTPException(status_code=500, detail="Cold start engine not initialized")
    playbook = engine.get_playbook(platform_id)
    if playbook is None:
        raise HTTPException(status_code=404, detail="No playbook for this platform")
    return _playbook_response(playbook)


@router.get("/platforms/{platform_id}/acquisition-plan")
def get_acquisition_plan(platform_id: str):
    engine = pipeline.acquisition_engine
    if engine is None:
        raise HTTPException(status_code=500, detail="Acquisition engine not initialized")
    plan = engine.get_plan(platform_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="No acquisition plan for this platform")
    return _plan_response(plan)


@router.post("/platforms/{platform_id}/acquisition-plan/refresh")
def refresh_acquisition_plan(platform_id: str):
    acq_engine = pipeline.acquisition_engine
    cs_engine = pipeline.cold_start_engine
    if acq_engine is None or cs_engine is None:
        raise HTTPException(status_code=500, detail="Engines not initialized")
    playbook = cs_engine.get_playbook(platform_id)
    if playbook is None:
        raise HTTPException(status_code=404, detail="No playbook for this platform — run cold start first")
    plan = acq_engine.refresh_plan(platform_id=platform_id, playbook=playbook)
    return _plan_response(plan)
