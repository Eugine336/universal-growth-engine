"""
Conversion Predictor

Predicts the probability that an identity will complete
a target conversion action within the next 7 days.

Signals used:
- Purchase intent signal strength
- Items saved (high-intent behavior)
- Search activity
- Session recency
- Past conversion history
- Engagement tier
"""

from __future__ import annotations

from core.behavior.schema import BehavioralProfile
from core.prediction.schema import Prediction, PredictionType
from .base import BasePredictor


class ConversionPredictor(BasePredictor):

    prediction_type = PredictionType.CONVERSION
    default_horizon_days = 7
    model_version = "conversion_rule_v1"

    def predict(self, profile: BehavioralProfile) -> Prediction:
        factors = {}

        interests = profile.interests
        rfm = profile.rfm
        eng = profile.engagement

        # --- Factor 1: Purchase intent signal ---
        intent = profile.get_intent_signal("purchase_intent")
        intent_strength = intent.strength if intent else 0.0
        factors["purchase_intent"] = intent_strength * 0.35

        # --- Factor 2: Items saved ---
        saved_count = len(interests.saved_item_ids)
        factors["items_saved"] = min(0.20, saved_count * 0.05)

        # --- Factor 3: Search activity ---
        search_count = len(interests.search_terms)
        factors["search_activity"] = min(0.15, search_count * 0.03)

        # --- Factor 4: Session recency ---
        days_inactive = profile.churn.days_inactive
        if days_inactive <= 1:
            factors["recency"] = 0.20
        elif days_inactive <= 3:
            factors["recency"] = 0.15
        elif days_inactive <= 7:
            factors["recency"] = 0.08
        else:
            factors["recency"] = 0.0

        # --- Factor 5: Past conversion history ---
        past_conversions = rfm.total_conversions
        factors["past_conversions"] = min(0.15, past_conversions * 0.03)

        # --- Factor 6: Engagement tier ---
        tier_bonus = {
            "power": 0.10,
            "active": 0.05,
            "warming": 0.02,
            "cold": 0.0,
        }
        factors["engagement_tier"] = tier_bonus.get(eng.tier, 0.0)

        score = sum(factors.values())
        score = max(0.0, min(1.0, score))

        confidence = min(0.85, 0.3 + (rfm.total_conversions * 0.05) + intent_strength * 0.2)
        label = self._label_from_score(score)

        explanation = (
            f"Conversion score {round(score, 2)}: "
            f"intent={round(intent_strength, 2)}, "
            f"saved={saved_count}, "
            f"searches={search_count}, "
            f"past_conversions={past_conversions}."
        )

        return self._make_prediction(
            profile=profile,
            score=score,
            confidence=confidence,
            label=label,
            factors={k: round(v, 4) for k, v in factors.items()},
            explanation=explanation,
        )
