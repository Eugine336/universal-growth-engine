"""
Churn Predictor

Predicts the probability that an identity will churn
(disengage permanently) within the next 30 days.

Signals used:
- Days since last active
- Session frequency decay (7d vs 30d)
- Friction event count
- Subscription cancellation
- Engagement tier
- RFM recency score
"""

from __future__ import annotations

from core.behavior.schema import BehavioralProfile
from core.prediction.schema import Prediction, PredictionType
from .base import BasePredictor


class ChurnPredictor(BasePredictor):

    prediction_type = PredictionType.CHURN
    default_horizon_days = 30
    model_version = "churn_rule_v1"

    def predict(self, profile: BehavioralProfile) -> Prediction:
        factors = {}
        score = 0.0

        eng = profile.engagement
        churn = profile.churn
        rfm = profile.rfm

        # --- Factor 1: Days inactive ---
        days_inactive = churn.days_inactive
        if days_inactive >= 90:
            factors["days_inactive"] = 0.40
        elif days_inactive >= 60:
            factors["days_inactive"] = 0.30
        elif days_inactive >= 30:
            factors["days_inactive"] = 0.20
        elif days_inactive >= 14:
            factors["days_inactive"] = 0.10
        else:
            factors["days_inactive"] = 0.0

        # --- Factor 2: Session frequency decay ---
        if eng.total_sessions > 0:
            decay = 0.0
            if eng.sessions_last_7d == 0 and eng.sessions_last_30d > 0:
                decay = 0.20
            elif eng.sessions_last_7d < eng.sessions_last_30d * 0.25:
                decay = 0.15
            factors["session_decay"] = decay
        else:
            factors["session_decay"] = 0.0

        # --- Factor 3: Friction events ---
        friction_score = min(0.25, churn.recent_friction_count * 0.08)
        factors["friction_events"] = friction_score

        # --- Factor 4: Subscription cancelled ---
        factors["subscription_cancelled"] = 0.30 if churn.cancelled_subscription else 0.0

        # --- Factor 5: Engagement tier ---
        tier_penalty = {
            "cold": 0.20,
            "warming": 0.10,
            "active": 0.0,
            "power": -0.10,
        }
        factors["engagement_tier"] = tier_penalty.get(eng.tier, 0.0)

        # --- Factor 6: RFM recency ---
        rfm_penalty = max(0.0, (5 - rfm.recency_score) * 0.03)
        factors["rfm_recency"] = rfm_penalty

        # Aggregate
        score = sum(factors.values())
        score = max(0.0, min(1.0, score))

        # Confidence: higher when we have more signal
        confidence = min(0.9, 0.3 + (eng.total_sessions * 0.05))

        explanation = self._explain(factors, score, days_inactive)
        label = self._label_from_score(score)

        return self._make_prediction(
            profile=profile,
            score=score,
            confidence=confidence,
            label=label,
            factors={k: round(v, 4) for k, v in factors.items()},
            explanation=explanation,
        )

    def _explain(self, factors: dict, score: float, days_inactive: float) -> str:
        parts = []
        if days_inactive >= 14:
            parts.append(f"inactive for {int(days_inactive)} days")
        if factors.get("subscription_cancelled", 0) > 0:
            parts.append("subscription was cancelled")
        if factors.get("friction_events", 0) > 0.1:
            parts.append("multiple friction events detected")
        if factors.get("session_decay", 0) > 0.1:
            parts.append("session frequency is declining")
        if not parts:
            parts.append("low churn signals detected")
        return f"Churn score {round(score, 2)}: " + "; ".join(parts) + "."
