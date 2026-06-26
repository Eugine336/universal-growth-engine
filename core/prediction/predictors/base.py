"""
Base Predictor Interface

All predictors implement this interface.
The engine calls predict(profile) and receives a Prediction.

Design principles:
- Stateless: predictors don't store state, they compute from profile
- Swappable: rule-based now, replace with ML model without changing callers
- Explainable: every prediction includes contributing factors
- Bounded: predictions carry a validity window
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta
from typing import Optional

from core.behavior.schema import BehavioralProfile
from core.prediction.schema import Prediction, PredictionType


class BasePredictor(ABC):
    """Abstract base class for all predictors."""

    model_version: str = "rule_v1"
    model_type: str = "rule_based"
    default_horizon_days: int = 30
    default_valid_hours: int = 24

    @property
    @abstractmethod
    def prediction_type(self) -> PredictionType:
        pass

    @abstractmethod
    def predict(self, profile: BehavioralProfile) -> Prediction:
        pass

    def _make_prediction(
        self,
        profile: BehavioralProfile,
        score: float,
        confidence: float,
        label: Optional[str],
        factors: dict,
        explanation: str,
    ) -> Prediction:
        return Prediction(
            identity_id=profile.identity_id,
            application_id=profile.application_id,
            type=self.prediction_type,
            score=round(max(0.0, min(1.0, score)), 4),
            confidence=round(max(0.0, min(1.0, confidence)), 4),
            label=label,
            factors=factors,
            explanation=explanation,
            model_version=self.model_version,
            model_type=self.model_type,
            horizon_days=self.default_horizon_days,
            valid_until=datetime.now(timezone.utc) + timedelta(hours=self.default_valid_hours),
        )

    def _label_from_score(self, score: float) -> str:
        if score >= 0.75:
            return "high"
        if score >= 0.4:
            return "medium"
        return "low"
