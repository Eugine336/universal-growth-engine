"""
UGIE Core — Prediction Engine

Responsibilities:
- Produce probability scores for future user behaviors
- Each predictor is standalone and swappable (rule-based now, ML-ready)
- Predictions feed directly into the decision engine
- All predictions are versioned and auditable

Predictors:
- ChurnPredictor        — will this user leave in the next N days?
- ConversionPredictor   — will they complete a target action?
- LTVPredictor          — what is their predicted lifetime value?
- UpsellPredictor       — will they upgrade or expand?
- ReferralPredictor     — will they refer someone?
- FraudPredictor        — are they behaving fraudulently?
"""

from .schema import (
    Prediction,
    PredictionType,
    PredictionSet,
    PredictionRequest,
)
from .engine import PredictionEngine
from .predictors.churn import ChurnPredictor
from .predictors.conversion import ConversionPredictor
from .predictors.ltv import LTVPredictor
from .predictors.upsell import UpsellPredictor
from .predictors.referral import ReferralPredictor
from .predictors.fraud import FraudPredictor

__all__ = [
    "Prediction",
    "PredictionType",
    "PredictionSet",
    "PredictionRequest",
    "PredictionEngine",
    "ChurnPredictor",
    "ConversionPredictor",
    "LTVPredictor",
    "UpsellPredictor",
    "ReferralPredictor",
    "FraudPredictor",
]
