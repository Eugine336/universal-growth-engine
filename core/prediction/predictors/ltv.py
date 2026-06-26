"""
LTV Predictor

Predicts the expected lifetime value of an identity
over the next 12 months.

Method: Simple projection from historical RFM data.
- Average order value × predicted future frequency
- Adjusted by churn probability and engagement tier
- Score represents projected 12-month value (not 0-1 probability)

Note: score field holds the projected LTV value (currency units),
not a probability. label indicates the LTV tier.
"""

from __future__ import annotations

from core.behavior.schema import BehavioralProfile
from core.prediction.schema import Prediction, PredictionType
from .base import BasePredictor


class LTVPredictor(BasePredictor):

    prediction_type = PredictionType.LTV
    default_horizon_days = 365
    model_version = "ltv_rule_v1"

    def predict(self, profile: BehavioralProfile) -> Prediction:
        rfm = profile.rfm
        eng = profile.engagement
        churn = profile.churn

        factors = {}

        # --- Base: Average order value ---
        avg_value = rfm.avg_monetary_value
        factors["avg_order_value"] = avg_value

        # --- Predicted purchase frequency (per year) ---
        # Use historical conversion rate as a proxy
        # If they've been a user for some time, annualize their conversions
        if eng.first_seen_at and profile.last_event_at:
            days_as_user = max(
                1,
                (profile.last_event_at - eng.first_seen_at).days
            )
            annual_frequency = (rfm.total_conversions / days_as_user) * 365
        else:
            annual_frequency = rfm.total_conversions * 2.0   # default assumption

        annual_frequency = max(0.0, annual_frequency)
        factors["predicted_annual_frequency"] = round(annual_frequency, 2)

        # --- Base projected LTV ---
        projected_ltv = avg_value * annual_frequency

        # --- Churn adjustment: reduce by churn risk ---
        churn_discount = {
            "low": 1.0,
            "medium": 0.75,
            "high": 0.5,
            "critical": 0.2,
        }
        churn_multiplier = churn_discount.get(churn.risk_level, 0.75)
        factors["churn_discount"] = churn_multiplier

        # --- Engagement multiplier ---
        tier_multiplier = {
            "power": 1.3,
            "active": 1.1,
            "warming": 0.9,
            "cold": 0.6,
        }
        eng_multiplier = tier_multiplier.get(eng.tier, 1.0)
        factors["engagement_multiplier"] = eng_multiplier

        # --- RFM segment adjustment ---
        segment_multiplier = {
            "champions": 1.4,
            "loyal": 1.2,
            "promising": 1.0,
            "at_risk": 0.7,
            "hibernating": 0.5,
            "lost": 0.2,
            "new": 0.9,
        }
        seg_multiplier = segment_multiplier.get(rfm.segment, 1.0)
        factors["segment_multiplier"] = seg_multiplier

        # Final LTV
        ltv = projected_ltv * churn_multiplier * eng_multiplier * seg_multiplier
        ltv = max(0.0, round(ltv, 2))

        # LTV label tiers
        if ltv >= 10000:
            label = "enterprise"
        elif ltv >= 1000:
            label = "high_value"
        elif ltv >= 100:
            label = "medium_value"
        elif ltv > 0:
            label = "low_value"
        else:
            label = "no_value"

        confidence = min(0.85, 0.2 + (rfm.total_conversions * 0.08))

        explanation = (
            f"Projected 12-month LTV: {ltv} "
            f"(avg_order={avg_value}, "
            f"annual_freq={round(annual_frequency, 1)}, "
            f"churn_discount={churn_multiplier}, "
            f"segment={rfm.segment})."
        )

        # LTV score is the raw value — normalize to 0-1 for the base field
        # but store raw in factors for consumers who need the currency value
        max_expected_ltv = 50000.0
        normalized_score = min(1.0, ltv / max_expected_ltv)

        result = self._make_prediction(
            profile=profile,
            score=normalized_score,
            confidence=confidence,
            label=label,
            factors={k: round(v, 4) if isinstance(v, float) else v
                     for k, v in factors.items()},
            explanation=explanation,
        )
        # Attach raw LTV value
        result.factors["ltv_raw"] = ltv
        return result
