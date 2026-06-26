"""
Fraud Predictor

Predicts the probability that an identity is exhibiting
fraudulent or policy-violating behavior.

Signals used:
- Login failure rate
- Multiple failed payments
- High dispute rate relative to transactions
- Rapid account creation patterns
- Refund abuse patterns
- Abnormal session patterns
"""

from __future__ import annotations

from core.behavior.schema import BehavioralProfile
from core.prediction.schema import Prediction, PredictionType
from .base import BasePredictor


class FraudPredictor(BasePredictor):

    prediction_type = PredictionType.FRAUD
    default_horizon_days = 7
    model_version = "fraud_rule_v1"

    def predict(self, profile: BehavioralProfile) -> Prediction:
        factors = {}

        rfm = profile.rfm
        eng = profile.engagement

        # --- Login failures ---
        login_failures = profile.get_event_count("LOGIN_FAILED")
        login_attempts = (
            login_failures + profile.get_event_count("LOGIN_SUCCESS")
        )
        if login_attempts > 0:
            failure_rate = login_failures / login_attempts
            factors["login_failure_rate"] = min(0.30, failure_rate * 0.30)
        else:
            factors["login_failure_rate"] = 0.0

        # --- Payment failures ---
        payment_failures = profile.get_event_count("PAYMENT_FAILED")
        payment_attempts = (
            payment_failures + profile.get_event_count("PAYMENT_COMPLETED")
        )
        if payment_attempts > 0:
            pf_rate = payment_failures / payment_attempts
            factors["payment_failure_rate"] = min(0.25, pf_rate * 0.25)
        else:
            factors["payment_failure_rate"] = 0.0

        # --- Dispute rate ---
        dispute_count = profile.get_event_count("DISPUTE_OPENED")
        if rfm.total_conversions > 0:
            dispute_rate = dispute_count / rfm.total_conversions
            factors["dispute_rate"] = min(0.25, dispute_rate * 0.25)
        else:
            factors["dispute_rate"] = min(0.15, dispute_count * 0.05)

        # --- Refund abuse ---
        refunds = profile.get_event_count("REFUND_INITIATED")
        if rfm.total_conversions > 0:
            refund_rate = refunds / rfm.total_conversions
            factors["refund_rate"] = min(0.20, refund_rate * 0.20)
        else:
            factors["refund_rate"] = 0.0

        # --- Abnormal session velocity ---
        # Many sessions in short time can indicate bot behavior
        if eng.sessions_last_7d > 50:
            factors["session_velocity"] = 0.15
        elif eng.sessions_last_7d > 20:
            factors["session_velocity"] = 0.08
        else:
            factors["session_velocity"] = 0.0

        # --- New account with high transaction velocity (card testing) ---
        if eng.total_sessions <= 2 and rfm.total_conversions >= 3:
            factors["rapid_transaction"] = 0.20
        else:
            factors["rapid_transaction"] = 0.0

        score = max(0.0, min(1.0, sum(factors.values())))

        # Confidence is lower for fraud — we need more signal
        confidence = min(0.70, 0.2 + login_failures * 0.05 + dispute_count * 0.08)

        label = self._label_from_score(score)

        top_factor = max(factors, key=factors.get) if factors else "none"
        explanation = (
            f"Fraud score {round(score, 2)}: "
            f"login_failures={login_failures}, "
            f"payment_failures={payment_failures}, "
            f"disputes={dispute_count}, "
            f"refunds={refunds}. "
            f"Top signal: {top_factor}."
        )

        return self._make_prediction(
            profile=profile,
            score=score,
            confidence=confidence,
            label=label,
            factors={k: round(v, 4) for k, v in factors.items()},
            explanation=explanation,
        )
