"""
Behavior Analyzer

Higher-level analysis on top of raw behavioral profiles.

While the BehaviorBuilder updates profiles event-by-event,
the Analyzer runs periodic batch computations:

- Recompute RFM scores across all profiles for an application
- Identify users entering churn windows
- Surface re-engagement candidates
- Compute engagement decay rates
- Identify power users for referral campaigns
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional

from .schema import BehavioralProfile, RFMScore
from .repository import BehaviorRepository

logger = logging.getLogger(__name__)


class BehaviorAnalyzer:
    """
    Periodic batch analyzer for behavioral profiles.

    Usage:
        analyzer = BehaviorAnalyzer(repository)
        report = analyzer.analyze_application("ucmc")
    """

    def __init__(self, repository: BehaviorRepository):
        self._repo = repository

    # ------------------------------------------------------------------
    # RFM recomputation
    # ------------------------------------------------------------------

    def recompute_rfm(self, application_id: str) -> int:
        """
        Recompute RFM scores for all profiles in an application.
        Returns count of profiles updated.
        """
        profiles = self._repo.list_by_application(application_id)
        if not profiles:
            return 0

        now = datetime.now(timezone.utc)

        # Collect raw values for percentile scoring
        recencies = []
        frequencies = []
        monetaries = []

        for p in profiles:
            # Recency: days since last conversion
            if p.rfm.days_since_last_conversion is not None:
                recencies.append(p.rfm.days_since_last_conversion)
            elif p.last_event_at:
                days = (now - p.last_event_at).days
                recencies.append(float(days))
                p.rfm.days_since_last_conversion = float(days)
            else:
                recencies.append(9999.0)

            frequencies.append(float(p.rfm.total_conversions))
            monetaries.append(p.rfm.total_monetary_value)

        # Score each profile 1-5 using quintiles
        for i, p in enumerate(profiles):
            p.rfm.recency_score = self._quintile_score(
                recencies[i], recencies, invert=True
            )
            p.rfm.frequency_score = self._quintile_score(
                frequencies[i], frequencies
            )
            p.rfm.monetary_score = self._quintile_score(
                monetaries[i], monetaries
            )
            p.rfm.combined_score = (
                p.rfm.recency_score +
                p.rfm.frequency_score +
                p.rfm.monetary_score
            )
            p.rfm.segment = self._rfm_segment(p.rfm)
            p.rfm.computed_at = now
            self._repo.save(p)

        logger.info(
            f"RFM recomputed | app={application_id} profiles={len(profiles)}"
        )
        return len(profiles)

    def _quintile_score(
        self,
        value: float,
        all_values: List[float],
        invert: bool = False,
    ) -> int:
        """Score a value 1-5 based on its position in the distribution."""
        if not all_values or max(all_values) == min(all_values):
            return 3
        sorted_vals = sorted(all_values)
        n = len(sorted_vals)
        idx = sorted_vals.index(value) if value in sorted_vals else 0
        percentile = idx / max(n - 1, 1)
        score = int(percentile * 4) + 1   # 1-5
        score = max(1, min(5, score))
        return (6 - score) if invert else score

    def _rfm_segment(self, rfm: RFMScore) -> str:
        r, f, m = rfm.recency_score, rfm.frequency_score, rfm.monetary_score
        combined = rfm.combined_score

        if r >= 4 and f >= 4 and m >= 4:
            return "champions"
        if f >= 4 and m >= 3:
            return "loyal"
        if r >= 4 and f <= 2:
            return "promising"
        if r <= 2 and f >= 3:
            return "at_risk"
        if r <= 2 and f <= 2:
            return "hibernating"
        if combined <= 4:
            return "lost"
        return "new"

    # ------------------------------------------------------------------
    # Churn window detection
    # ------------------------------------------------------------------

    def detect_churn_windows(
        self,
        application_id: str,
        inactivity_threshold_days: int = 14,
    ) -> List[BehavioralProfile]:
        """
        Find profiles entering a churn risk window.
        These are users who were active but have gone quiet.
        """
        now = datetime.now(timezone.utc)
        threshold = now - timedelta(days=inactivity_threshold_days)
        at_risk = []

        for profile in self._repo.list_by_application(application_id):
            last_active = profile.engagement.last_active_at
            if not last_active:
                continue

            days_inactive = (now - last_active).days
            profile.churn.days_inactive = float(days_inactive)

            # Update risk score for inactivity
            if days_inactive >= inactivity_threshold_days:
                if profile.engagement.total_sessions >= 3:
                    # Was genuinely active — now silent
                    profile.churn.engagement_decay_rate = min(
                        1.0,
                        days_inactive / 90.0
                    )
                    if profile.churn.risk_score < 0.3:
                        profile.churn.risk_score = min(
                            1.0,
                            profile.churn.risk_score + (days_inactive / 90.0) * 0.5
                        )
                    profile.churn.risk_level = self._risk_level(profile.churn.risk_score)
                    self._repo.save(profile)
                    at_risk.append(profile)

        logger.info(
            f"Churn window detection | app={application_id} "
            f"at_risk_count={len(at_risk)} threshold={inactivity_threshold_days}d"
        )
        return at_risk

    # ------------------------------------------------------------------
    # Re-engagement candidates
    # ------------------------------------------------------------------

    def find_reengagement_candidates(
        self,
        application_id: str,
        min_past_sessions: int = 2,
        inactive_days_min: int = 14,
        inactive_days_max: int = 90,
    ) -> List[BehavioralProfile]:
        """
        Find users worth re-engaging:
        - Previously active (min_past_sessions or more sessions)
        - Currently inactive (between min and max days)
        - Not yet lost
        """
        now = datetime.now(timezone.utc)
        candidates = []

        for profile in self._repo.list_by_application(application_id):
            if profile.engagement.total_sessions < min_past_sessions:
                continue
            last_active = profile.engagement.last_active_at
            if not last_active:
                continue
            days_inactive = (now - last_active).days
            if inactive_days_min <= days_inactive <= inactive_days_max:
                if profile.rfm.segment != "lost":
                    candidates.append(profile)

        return candidates

    # ------------------------------------------------------------------
    # Power users (referral / advocacy candidates)
    # ------------------------------------------------------------------

    def find_power_users(
        self,
        application_id: str,
        min_sessions_7d: int = 5,
        min_conversions: int = 2,
    ) -> List[BehavioralProfile]:
        """Find power users suitable for referral or advocacy campaigns."""
        return [
            p for p in self._repo.list_by_application(application_id)
            if (
                p.engagement.sessions_last_7d >= min_sessions_7d
                and p.rfm.total_conversions >= min_conversions
                and p.churn.risk_level == "low"
            )
        ]

    # ------------------------------------------------------------------
    # Application-level report
    # ------------------------------------------------------------------

    def analyze_application(self, application_id: str) -> Dict:
        """
        Full behavioral analysis for an application.
        Returns a structured report with key segments and signals.
        """
        profiles = self._repo.list_by_application(application_id)
        if not profiles:
            return {"application_id": application_id, "total_profiles": 0}

        churn_windows = self.detect_churn_windows(application_id)
        reengagement = self.find_reengagement_candidates(application_id)
        power_users = self.find_power_users(application_id)

        stats = self._repo.stats(application_id)
        stats.update({
            "application_id": application_id,
            "churn_window_count": len(churn_windows),
            "reengagement_candidates": len(reengagement),
            "power_users": len(power_users),
        })
        return stats

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _risk_level(self, score: float) -> str:
        if score >= 0.8:
            return "critical"
        if score >= 0.5:
            return "high"
        if score >= 0.25:
            return "medium"
        return "low"
