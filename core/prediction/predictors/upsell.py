"""
Upsell Predictor

Predicts the probability that an identity will upgrade,
expand their subscription, or purchase a higher-tier product.
"""

from __future__ import annotations

from core.behavior.schema import BehavioralProfile
from core.prediction.schema import Prediction, PredictionType
from .base import BasePredictor


class UpsellPredictor(BasePredictor):

    prediction_type = PredictionType.UPSELL
    default_horizon_days = 30
    model_version = "upsell_rule_v1"

    def predict(self, profile: BehavioralProfile) -> Prediction:
        factors = {}
        eng = profile.engagement
        rfm = profile.rfm

        # --- Upsell intent signal ---
        signal = profile.get_intent_signal("upsell_ready")
        signal_strength = signal.strength if signal else 0.0
        factors["upsell_signal"] = signal_strength * 0.35

        # --- Feature breadth: using many features suggests readiness for more ---
        feature_breadth = len(eng.unique_features_used)
        factors["feature_breadth"] = min(0.20, feature_breadth * 0.04)

        # --- Engagement tier ---
        tier_bonus = {"power": 0.20, "active": 0.10, "warming": 0.03, "cold": 0.0}
        factors["engagement_tier"] = tier_bonus.get(eng.tier, 0.0)

        # --- Past conversions (loyalty signal) ---
        factors["conversion_history"] = min(0.15, rfm.total_conversions * 0.03)

        # --- RFM segment ---
        segment_bonus = {
            "champions": 0.20, "loyal": 0.15, "promising": 0.05,
            "at_risk": -0.05, "hibernating": -0.10, "lost": -0.15, "new": 0.02,
        }
        factors["rfm_segment"] = segment_bonus.get(rfm.segment, 0.0)

        # --- Low churn risk is a positive signal ---
        churn_bonus = {
            "low": 0.10, "medium": 0.02, "high": -0.05, "critical": -0.15
        }
        factors["churn_risk"] = churn_bonus.get(profile.churn.risk_level, 0.0)

        score = max(0.0, min(1.0, sum(factors.values())))
        confidence = min(0.80, 0.3 + signal_strength * 0.3 + rfm.total_conversions * 0.04)
        label = self._label_from_score(score)

        return self._make_prediction(
            profile=profile,
            score=score,
            confidence=confidence,
            label=label,
            factors={k: round(v, 4) for k, v in factors.items()},
            explanation=(
                f"Upsell score {round(score, 2)}: "
                f"signal={round(signal_strength, 2)}, "
                f"features_used={feature_breadth}, "
                f"segment={rfm.segment}."
            ),
        )
