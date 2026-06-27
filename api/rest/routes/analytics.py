"""Analytics endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter

from api.rest.app import pipeline

router = APIRouter(tags=["analytics"])


def _engine():
    from core.analytics.engine import AnalyticsEngine

    return AnalyticsEngine(
        behavior_repo=pipeline.behavior_repo,
        prediction_engine=pipeline.prediction_engine,
        experimentation_engine=pipeline.experimentation_engine,
        referral_engine=pipeline.referral_engine,
        audience_engine=pipeline.audience_engine,
        identity_graph=pipeline.identity_graph,
        cross_platform_manager=pipeline.cross_platform_manager,
    )


@router.get("/analytics/dashboard")
def get_dashboard(platform_id: Optional[str] = "default"):
    return _engine().get_dashboard(platform_id).model_dump()


@router.get("/analytics/funnel")
def get_funnel(platform_id: Optional[str] = "default"):
    return _engine().get_funnel_metrics(platform_id).model_dump()


@router.get("/analytics/engagement")
def get_engagement(platform_id: Optional[str] = "default"):
    return _engine().get_engagement_breakdown(platform_id).model_dump()


@router.get("/analytics/rfm")
def get_rfm(platform_id: Optional[str] = "default"):
    return _engine().get_rfm_breakdown(platform_id).model_dump()


@router.get("/analytics/churn")
def get_churn(platform_id: Optional[str] = "default"):
    return _engine().get_churn_breakdown(platform_id).model_dump()


@router.get("/analytics/predictions")
def get_predictions(platform_id: Optional[str] = "default"):
    summaries = _engine().get_prediction_summary(platform_id)
    return [s.model_dump() for s in summaries]


@router.get("/analytics/experiments")
def get_experiments(platform_id: Optional[str] = "default"):
    return _engine().get_experiment_summary(platform_id).model_dump()


@router.get("/analytics/referrals")
def get_referrals(platform_id: Optional[str] = "default"):
    return _engine().get_referral_summary(platform_id).model_dump()


@router.get("/analytics/audiences")
def get_audiences(platform_id: Optional[str] = "default"):
    return _engine().get_audience_summary(platform_id).model_dump()


@router.get("/analytics/growth")
def get_growth(platform_id: Optional[str] = "default"):
    return _engine().get_growth_metrics(platform_id)
