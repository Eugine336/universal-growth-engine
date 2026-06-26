"""
Referral Predictor

Predicts the probability that an identity will refer
another user to the platform within the next 30 days.
"""

from __future__ import annotations

from core.behavior.schema import BehavioralProfile
from core.prediction.schema import Prediction, PredictionType
from .base import BasePredictor


class ReferralPredictor(BasePredictor):

    prediction_type = PredictionType.REFERRAL
    default_horizon_days = 30
    model_version = "referral_rule_v1"

    def predict(self, profile: BehavioralProfile) -> Prediction:
        factors = {}
        eng = profile.engagement
        rfm = profile.rfm
        interests = profile.interests

        # --- Referral intent signal ---
        signal = profile.get_intent_signal("referral_intent")
        signal_strength = signal.strength if signal else 0.0
        factors["referral_signal"] = signal_strength * 0.40

        # --- Sharing behavior ---
        share_count = len(interests.shared_item_ids)
        factors["sharing_behavior"] = min(0.20, share_count * 0.07)

        # --- High engagement = more likely to advocate ---
        tier_bonus = {"power": 0.20, "active": 0.10, "warming": 0.03, "cold": 0.0}
        factors["engagement_tier"] = tier_bonus.get(eng.tier, 0.0)

        # --- Satisfaction proxy: conversions without disputes ---
        dispute_count = profile.get_event_count("DISPUTE_OPENED")
        satisfaction = max(0.0, rfm.total_conversions - dispute_count * 2)
        factors["satisfaction_proxy"] = min(0.15, satisfaction * 0.03)

        # --- Champions and loyal users refer more ---
        segment_bonus = {
            "champions": 0.15, "loyal": 0.10, "promising": 0.05,
            "new": 0.02, "at_risk": -0.05, "hibernating": -0.10, "lost": -0.20,
        }
        factors["rfm_segment"] = segment_bonus.get(rfm.segment, 0.0)

        score = max(0.0, min(1.0, sum(factors.values())))
        confidence = min(0.75, 0.25 + signal_strength * 0.35 + share_count * 0.05)
        label = self._label_from_score(score)

        return self._make_prediction(
            profile=profile,
            score=score,
            confidence=confidence,
            label=label,
            factors={k: round(v, 4) for k, v in factors.items()},
            explanation=(
                f"Referral score {round(score, 2)}: "
                f"signal={round(signal_strength, 2)}, "
                f"shares={share_count}, "
                f"segment={rfm.segment}."
            ),
        )
