"""
Prediction Engine

Orchestrates all predictors. Given a behavioral profile,
runs all requested predictors and returns a PredictionSet.

The engine:
- Maintains a registry of predictors
- Runs predictors in parallel (or sequence)
- Caches prediction sets with TTL
- Exposes a simple predict() interface to the decision engine
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Type

from core.behavior.schema import BehavioralProfile
from core.behavior.repository import BehaviorRepository

from .schema import Prediction, PredictionSet, PredictionType, PredictionRequest
from .predictors.base import BasePredictor
from .predictors.churn import ChurnPredictor
from .predictors.conversion import ConversionPredictor
from .predictors.ltv import LTVPredictor
from .predictors.upsell import UpsellPredictor
from .predictors.referral import ReferralPredictor
from .predictors.fraud import FraudPredictor

logger = logging.getLogger(__name__)


class PredictionEngine:
    """
    Runs all registered predictors against a behavioral profile
    and returns a complete PredictionSet.

    Usage:
        engine = PredictionEngine(behavior_repository)

        prediction_set = engine.predict(
            identity_id="identity_001",
            application_id="ucmc",
        )

        churn = prediction_set.get(PredictionType.CHURN)
        print(churn.score, churn.label)
    """

    def __init__(self, behavior_repository: BehaviorRepository):
        self._behavior_repo = behavior_repository
        self._predictors: Dict[PredictionType, BasePredictor] = {}
        self._cache: Dict[str, PredictionSet] = {}

        # Register all built-in predictors
        self._register_defaults()
        logger.info("PredictionEngine initialized")

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, predictor: BasePredictor) -> None:
        """Register or replace a predictor."""
        self._predictors[predictor.prediction_type] = predictor
        logger.info(
            f"Registered predictor: {predictor.prediction_type.value} "
            f"({predictor.model_version})"
        )

    def _register_defaults(self) -> None:
        for cls in [
            ChurnPredictor,
            ConversionPredictor,
            LTVPredictor,
            UpsellPredictor,
            ReferralPredictor,
            FraudPredictor,
        ]:
            self.register(cls())

    # ------------------------------------------------------------------
    # Core predict
    # ------------------------------------------------------------------

    def predict(
        self,
        identity_id: str,
        application_id: str,
        prediction_types: Optional[List[PredictionType]] = None,
        force_refresh: bool = False,
    ) -> Optional[PredictionSet]:
        """
        Run predictions for a given identity.
        Returns a PredictionSet or None if no behavioral profile exists.
        """
        # Fetch behavioral profile
        profile = self._behavior_repo.get(identity_id, application_id)
        if not profile:
            logger.warning(
                f"No behavioral profile found for "
                f"identity={identity_id} app={application_id}"
            )
            return None

        return self.predict_from_profile(
            profile=profile,
            prediction_types=prediction_types,
            force_refresh=force_refresh,
        )

    def predict_from_profile(
        self,
        profile: BehavioralProfile,
        prediction_types: Optional[List[PredictionType]] = None,
        force_refresh: bool = False,
    ) -> PredictionSet:
        """Run predictions directly from a behavioral profile."""
        types_to_run = prediction_types or list(PredictionType)

        # Check cache
        cache_key = self._cache_key(profile.identity_id, profile.application_id)
        if not force_refresh and cache_key in self._cache:
            cached = self._cache[cache_key]
            # Return cached if all requested types are present and valid
            if all(
                cached.get(t) is not None and cached.get(t).is_valid()
                for t in types_to_run
            ):
                logger.debug(f"Cache hit for {cache_key}")
                return cached

        # Run predictors
        prediction_set = PredictionSet(
            identity_id=profile.identity_id,
            application_id=profile.application_id,
        )

        for ptype in types_to_run:
            predictor = self._predictors.get(ptype)
            if not predictor:
                logger.warning(f"No predictor registered for type: {ptype.value}")
                continue
            try:
                prediction = predictor.predict(profile)
                prediction_set.set(prediction)
                logger.debug(
                    f"Predicted {ptype.value} | identity={profile.identity_id} "
                    f"score={prediction.score} label={prediction.label}"
                )
            except Exception as e:
                logger.error(
                    f"Predictor {ptype.value} failed for "
                    f"identity={profile.identity_id}: {e}"
                )

        # Cache result
        self._cache[cache_key] = prediction_set

        logger.info(
            f"Predictions complete | identity={profile.identity_id} "
            f"app={profile.application_id} "
            f"types={[t.value for t in types_to_run]}"
        )

        return prediction_set

    def predict_one(
        self,
        identity_id: str,
        application_id: str,
        prediction_type: PredictionType,
    ) -> Optional[Prediction]:
        """Run a single predictor for an identity."""
        profile = self._behavior_repo.get(identity_id, application_id)
        if not profile:
            return None
        predictor = self._predictors.get(prediction_type)
        if not predictor:
            return None
        return predictor.predict(profile)

    def predict_batch(
        self,
        application_id: str,
        prediction_types: Optional[List[PredictionType]] = None,
    ) -> List[PredictionSet]:
        """Run predictions for all identities in an application."""
        profiles = self._behavior_repo.list_by_application(application_id)
        results = []
        for profile in profiles:
            ps = self.predict_from_profile(profile, prediction_types)
            results.append(ps)
        logger.info(
            f"Batch predictions complete | app={application_id} "
            f"count={len(results)}"
        )
        return results

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    def invalidate_cache(self, identity_id: str, application_id: str) -> None:
        key = self._cache_key(identity_id, application_id)
        self._cache.pop(key, None)

    def clear_cache(self) -> None:
        self._cache.clear()

    def _cache_key(self, identity_id: str, application_id: str) -> str:
        return f"{application_id}:{identity_id}"

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def stats(self) -> Dict:
        return {
            "registered_predictors": [t.value for t in self._predictors],
            "cache_size": len(self._cache),
        }
