"""
Prediction Schema

A Prediction is a probability score for a future outcome.

Every prediction is:
- Typed (churn, conversion, ltv, upsell, referral, fraud)
- Scored (0.0 → 1.0 probability, or a continuous value for LTV)
- Versioned (model version tracked for auditability)
- Explainable (contributing factors recorded)
- Time-bounded (valid_until tells consumers when to refresh)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PredictionType(str, Enum):
    CHURN = "churn"
    CONVERSION = "conversion"
    LTV = "ltv"
    UPSELL = "upsell"
    REFERRAL = "referral"
    FRAUD = "fraud"


class Prediction(BaseModel):
    """
    A single prediction output for one identity.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    identity_id: str
    application_id: str
    type: PredictionType

    # Core output
    score: float = Field(..., ge=0.0, description="Probability 0.0–1.0, or value for LTV")
    confidence: float = Field(0.5, ge=0.0, le=1.0, description="Model confidence in this score")
    label: Optional[str] = None          # Human-readable label e.g. "high_risk", "champion"

    # Explainability
    factors: Dict[str, float] = Field(
        default_factory=dict,
        description="Contributing factors and their weights"
    )
    explanation: str = ""

    # Model metadata
    model_version: str = "rule_v1"
    model_type: str = "rule_based"       # rule_based | logistic | xgboost | neural

    # Validity
    predicted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    valid_until: Optional[datetime] = None
    horizon_days: Optional[int] = None   # Prediction horizon e.g. 30 days for churn

    def is_valid(self) -> bool:
        if self.valid_until is None:
            return True
        return datetime.now(timezone.utc) < self.valid_until

    def is_high_risk(self, threshold: float = 0.7) -> bool:
        return self.score >= threshold

    def to_summary(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "score": round(self.score, 4),
            "confidence": round(self.confidence, 4),
            "label": self.label,
            "predicted_at": self.predicted_at.isoformat(),
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
        }


class PredictionSet(BaseModel):
    """
    A complete set of predictions for one identity at one point in time.
    All predictors run in one pass — results collected here.
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    identity_id: str
    application_id: str
    predictions: Dict[str, Prediction] = Field(default_factory=dict)
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def get(self, prediction_type: PredictionType) -> Optional[Prediction]:
        return self.predictions.get(prediction_type.value)

    def set(self, prediction: Prediction) -> None:
        self.predictions[prediction.type.value] = prediction

    def all_scores(self) -> Dict[str, float]:
        return {k: round(v.score, 4) for k, v in self.predictions.items()}

    def highest_risk(self) -> Optional[Prediction]:
        if not self.predictions:
            return None
        return max(self.predictions.values(), key=lambda p: p.score)


class PredictionRequest(BaseModel):
    """
    A request to run predictions for a specific identity.
    """
    identity_id: str
    application_id: str
    prediction_types: List[PredictionType] = Field(
        default_factory=lambda: list(PredictionType)
    )
    context: Dict[str, Any] = Field(default_factory=dict)
