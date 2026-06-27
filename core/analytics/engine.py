"""
Analytics Engine

Read-only aggregation layer that queries all UGIE subsystems
and computes dashboard metrics for a given platform.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from core.audience.engine import AudienceEngine
from core.behavior.repository import BehaviorRepository
from core.experimentation.engine import ExperimentationEngine
from core.experimentation.schema import ExperimentStatus
from core.identity.cross_platform import CrossPlatformManager
from core.identity.graph import IdentityGraph
from core.prediction.engine import PredictionEngine
from core.prediction.schema import PredictionType
from core.referral.engine import ReferralEngine

from .schema import (
    AudienceSummary,
    ChurnBreakdown,
    EngagementBreakdown,
    ExperimentSummary,
    FunnelMetrics,
    PlatformDashboard,
    PredictionSummary,
    ReferralSummary,
    RFMBreakdown,
)

logger = logging.getLogger(__name__)


class AnalyticsEngine:

    def __init__(
        self,
        behavior_repo: BehaviorRepository,
        prediction_engine: PredictionEngine,
        experimentation_engine: ExperimentationEngine,
        referral_engine: ReferralEngine,
        audience_engine: AudienceEngine,
        identity_graph: IdentityGraph,
        cross_platform_manager: CrossPlatformManager,
    ):
        self._behavior_repo = behavior_repo
        self._prediction_engine = prediction_engine
        self._experimentation_engine = experimentation_engine
        self._referral_engine = referral_engine
        self._audience_engine = audience_engine
        self._identity_graph = identity_graph
        self._cross_platform_manager = cross_platform_manager
        logger.info("AnalyticsEngine initialized")

    def get_dashboard(self, platform_id: str) -> PlatformDashboard:
        return PlatformDashboard(
            platform_id=platform_id,
            funnel=self.get_funnel_metrics(platform_id),
            engagement=self.get_engagement_breakdown(platform_id),
            rfm=self.get_rfm_breakdown(platform_id),
            churn=self.get_churn_breakdown(platform_id),
            predictions=self.get_prediction_summary(platform_id),
            experiments=self.get_experiment_summary(platform_id),
            referrals=self.get_referral_summary(platform_id),
            audiences=self.get_audience_summary(platform_id),
            identity_stats=self._identity_graph.stats(),
            cross_platform=self._cross_platform_manager.stats(),
        )

    def get_funnel_metrics(self, platform_id: str) -> FunnelMetrics:
        profiles = self._behavior_repo.list_by_application(platform_id)
        total = len(profiles)
        if total == 0:
            return FunnelMetrics()

        registered = sum(
            1 for p in profiles if p.get_event_count("USER_REGISTERED") > 0
        )
        activated = sum(
            1 for p in profiles if p.engagement.tier in ("warming", "active", "power")
        )
        converted = sum(1 for p in profiles if p.rfm.total_conversions > 0)
        retained = sum(
            1 for p in profiles if p.engagement.tier in ("active", "power")
        )

        return FunnelMetrics(
            total_identities=total,
            registered=registered,
            activated=activated,
            converted=converted,
            retained=retained,
            registration_to_activation_rate=(
                round(activated / registered, 4) if registered > 0 else 0.0
            ),
            activation_to_conversion_rate=(
                round(converted / activated, 4) if activated > 0 else 0.0
            ),
            conversion_to_retention_rate=(
                round(retained / converted, 4) if converted > 0 else 0.0
            ),
            overall_conversion_rate=(
                round(converted / total, 4) if total > 0 else 0.0
            ),
        )

    def get_engagement_breakdown(self, platform_id: str) -> EngagementBreakdown:
        profiles = self._behavior_repo.list_by_application(platform_id)
        counts: Dict[str, int] = {"cold": 0, "warming": 0, "active": 0, "power": 0}
        for p in profiles:
            tier = p.engagement.tier
            if tier in counts:
                counts[tier] += 1
        return EngagementBreakdown(
            cold=counts["cold"],
            warming=counts["warming"],
            active=counts["active"],
            power=counts["power"],
            total=len(profiles),
        )

    def get_rfm_breakdown(self, platform_id: str) -> RFMBreakdown:
        profiles = self._behavior_repo.list_by_application(platform_id)
        counts: Dict[str, int] = {
            "new": 0,
            "promising": 0,
            "loyal": 0,
            "champions": 0,
            "at_risk": 0,
            "hibernating": 0,
            "lost": 0,
        }
        for p in profiles:
            seg = p.rfm.segment
            if seg in counts:
                counts[seg] += 1
        return RFMBreakdown(
            new=counts["new"],
            promising=counts["promising"],
            loyal=counts["loyal"],
            champions=counts["champions"],
            at_risk=counts["at_risk"],
            hibernating=counts["hibernating"],
            lost=counts["lost"],
            total=len(profiles),
        )

    def get_churn_breakdown(self, platform_id: str) -> ChurnBreakdown:
        profiles = self._behavior_repo.list_by_application(platform_id)
        counts: Dict[str, int] = {"low": 0, "medium": 0, "high": 0, "critical": 0}
        for p in profiles:
            risk = p.churn.risk_level
            if risk in counts:
                counts[risk] += 1
        return ChurnBreakdown(
            low=counts["low"],
            medium=counts["medium"],
            high=counts["high"],
            critical=counts["critical"],
            total=len(profiles),
        )

    def get_prediction_summary(self, platform_id: str) -> List[PredictionSummary]:
        prediction_sets = self._prediction_engine.predict_batch(
            application_id=platform_id,
        )
        type_scores: Dict[str, List[float]] = {}
        for ps in prediction_sets:
            for ptype in PredictionType:
                pred = ps.get(ptype)
                if pred is not None:
                    type_scores.setdefault(ptype.value, []).append(pred.score)

        summaries = []
        for ptype_val, scores in type_scores.items():
            total = len(scores)
            avg = round(sum(scores) / total, 4) if total > 0 else 0.0
            high = sum(1 for s in scores if s >= 0.7)
            medium = sum(1 for s in scores if 0.3 <= s < 0.7)
            low = sum(1 for s in scores if s < 0.3)
            summaries.append(
                PredictionSummary(
                    prediction_type=ptype_val,
                    total_predictions=total,
                    avg_score=avg,
                    high_risk_count=high,
                    medium_risk_count=medium,
                    low_risk_count=low,
                )
            )
        return summaries

    def get_experiment_summary(self, platform_id: str) -> ExperimentSummary:
        all_exps = self._experimentation_engine.list_experiments(
            application_id=platform_id
        )
        running = sum(1 for e in all_exps if e.status == ExperimentStatus.RUNNING)
        completed = sum(1 for e in all_exps if e.status == ExperimentStatus.COMPLETED)
        draft = sum(1 for e in all_exps if e.status == ExperimentStatus.DRAFT)
        paused = sum(1 for e in all_exps if e.status == ExperimentStatus.PAUSED)

        experiment_details = []
        for exp in all_exps:
            results = self._experimentation_engine.get_results(exp.id)
            experiment_details.append(
                {
                    "id": exp.id,
                    "name": exp.name,
                    "status": exp.status.value,
                    "variants": results.get("variants", {}),
                }
            )

        return ExperimentSummary(
            total_experiments=len(all_exps),
            running=running,
            completed=completed,
            draft=draft,
            paused=paused,
            experiments=experiment_details,
        )

    def get_referral_summary(self, platform_id: str) -> ReferralSummary:
        stats = self._referral_engine.stats()
        return ReferralSummary(
            total_programs=stats.get("total_programs", 0),
            total_codes=stats.get("total_codes", 0),
            total_referrals=stats.get("total_referrals", 0),
            referrals_by_status=stats.get("referrals_by_status", {}),
        )

    def get_audience_summary(self, platform_id: str) -> AudienceSummary:
        audiences = self._audience_engine.list_audiences(platform_id)
        by_status: Dict[str, int] = {}
        for a in audiences:
            by_status[a.status] = by_status.get(a.status, 0) + 1
        return AudienceSummary(
            total_audiences=len(audiences),
            by_status=by_status,
        )

    def get_growth_metrics(self, platform_id: str) -> Dict[str, Any]:
        profiles = self._behavior_repo.list_by_application(platform_id)
        total = len(profiles)
        now = datetime.now(timezone.utc)
        cutoff_7d = now - timedelta(days=7)
        cutoff_30d = now - timedelta(days=30)

        new_7d = sum(1 for p in profiles if p.created_at >= cutoff_7d)
        new_30d = sum(1 for p in profiles if p.created_at >= cutoff_30d)
        active_7d = sum(
            1 for p in profiles if p.engagement.tier in ("active", "power")
        )

        return {
            "total_users": total,
            "new_users_7d": new_7d,
            "new_users_30d": new_30d,
            "active_users": active_7d,
            "dau_mau_ratio": (
                round(active_7d / total, 4) if total > 0 else 0.0
            ),
        }
