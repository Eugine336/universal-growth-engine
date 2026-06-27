"""
UGIE REST API

FastAPI application providing HTTP endpoints for the Universal Growth Engine.
Loads domain configs from UGIE_CONFIG_DIR on startup.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import FastAPI

from core.action.connector import ConnectorRegistry
from core.action.orchestrator import ActionOrchestrator
from core.audience.engine import AudienceEngine
from core.audience.exporter import AudienceExporter
from core.behavior.builder import BehaviorBuilder
from core.behavior.repository import BehaviorRepository
from core.config.loader import DomainConfigLoader
from core.decision.engine import DecisionEngine
from core.decision.policy import PolicyRegistry
from core.entity.registry import EntityRegistry
from core.entity.repository import EntityRepository
from core.entity.state import EntityStateMachine
from core.events.bus import EventBus
from core.events.validator import EventValidator
from core.experimentation.engine import ExperimentationEngine
from core.identity.graph import IdentityGraph
from core.identity.resolver import IdentityResolver
from core.ingest.transformer import InboundTransformerRegistry
from core.ingest.sources.generic import GenericTransformer
from core.ingest.sources.paystack import PaystackTransformer
from core.ingest.sources.shopify import ShopifyTransformer
from core.ingest.sources.stripe import StripeTransformer
from core.platform.registry import PlatformRegistry
from core.prediction.engine import PredictionEngine
from core.referral.engine import ReferralEngine

logger = logging.getLogger(__name__)


class Pipeline:
    """Holds all engine components wired together."""

    def __init__(self):
        self.event_bus: Optional[EventBus] = None
        self.identity_graph: Optional[IdentityGraph] = None
        self.identity_resolver: Optional[IdentityResolver] = None
        self.behavior_builder: Optional[BehaviorBuilder] = None
        self.behavior_repo: Optional[BehaviorRepository] = None
        self.prediction_engine: Optional[PredictionEngine] = None
        self.decision_engine: Optional[DecisionEngine] = None
        self.action_orchestrator: Optional[ActionOrchestrator] = None
        self.entity_repo: Optional[EntityRepository] = None
        self.connector_registry: Optional[ConnectorRegistry] = None
        self.config_loader: Optional[DomainConfigLoader] = None
        self.experimentation_engine: Optional[ExperimentationEngine] = None
        self.audience_engine: Optional[AudienceEngine] = None
        self.audience_exporter: Optional[AudienceExporter] = None
        self.platform_registry: Optional[PlatformRegistry] = None
        self.ingest_registry: Optional[InboundTransformerRegistry] = None
        self.referral_engine: Optional[ReferralEngine] = None


pipeline = Pipeline()


def create_app(db_url: Optional[str] = None) -> FastAPI:
    logging.basicConfig(level=logging.INFO)

    config_dir = os.environ.get("UGIE_CONFIG_DIR", "domain/examples")

    entity_registry = EntityRegistry()
    state_machine = EntityStateMachine()
    validator = EventValidator()
    policy_registry = PolicyRegistry()
    connector_registry = ConnectorRegistry()
    referral_engine = ReferralEngine()

    loader = DomainConfigLoader(
        entity_registry=entity_registry,
        state_machine=state_machine,
        event_validator=validator,
        policy_registry=policy_registry,
        connector_registry=connector_registry,
        referral_engine=referral_engine,
    )
    loader.load_directory(config_dir)

    event_bus = EventBus(validator=validator)
    identity_graph = IdentityGraph()
    identity_resolver = IdentityResolver(identity_graph)
    behavior_builder = BehaviorBuilder()
    behavior_repo = BehaviorRepository()
    prediction_engine = PredictionEngine(behavior_repo)
    experimentation_engine = ExperimentationEngine()
    decision_engine = DecisionEngine(
        behavior_repo=behavior_repo,
        prediction_engine=prediction_engine,
        policy_registry=policy_registry,
        experimentation_engine=experimentation_engine,
    )
    action_orchestrator = ActionOrchestrator(
        connector_registry=connector_registry,
    )
    entity_repo = EntityRepository()

    audience_engine = AudienceEngine(behavior_repo)
    audience_exporter = AudienceExporter(audience_engine, behavior_repo)

    from connectors.meta.connector import MetaAdsConnector
    from connectors.google.connector import GoogleAdsConnector
    from connectors.tiktok.connector import TikTokAdsConnector
    from connectors.linkedin.connector import LinkedInAdsConnector

    connector_registry.register(MetaAdsConnector())
    connector_registry.register(GoogleAdsConnector())
    connector_registry.register(TikTokAdsConnector())
    connector_registry.register(LinkedInAdsConnector())
    platform_registry = PlatformRegistry()

    ingest_registry = InboundTransformerRegistry()
    ingest_registry.register(StripeTransformer())
    ingest_registry.register(PaystackTransformer())
    ingest_registry.register(ShopifyTransformer())
    ingest_registry.register(GenericTransformer())

    pipeline.event_bus = event_bus
    pipeline.identity_graph = identity_graph
    pipeline.identity_resolver = identity_resolver
    pipeline.behavior_builder = behavior_builder
    pipeline.behavior_repo = behavior_repo
    pipeline.prediction_engine = prediction_engine
    pipeline.decision_engine = decision_engine
    pipeline.action_orchestrator = action_orchestrator
    pipeline.entity_repo = entity_repo
    pipeline.connector_registry = connector_registry
    pipeline.config_loader = loader
    pipeline.experimentation_engine = experimentation_engine
    pipeline.audience_engine = audience_engine
    pipeline.audience_exporter = audience_exporter
    pipeline.platform_registry = platform_registry
    pipeline.ingest_registry = ingest_registry
    pipeline.referral_engine = referral_engine

    from api.rest.routes import (
        health_router,
        events_router,
        entities_router,
        identities_router,
        decisions_router,
        webhooks_router,
        experiments_router,
        audiences_router,
        platforms_router,
        ingest_router,
        referrals_router,
    )

    app = FastAPI(
        title="Universal Growth Engine",
        version="0.1.0",
        description="Event-driven behavioral intelligence engine",
    )

    app.include_router(health_router, prefix="/api/v1")
    app.include_router(events_router, prefix="/api/v1")
    app.include_router(entities_router, prefix="/api/v1")
    app.include_router(identities_router, prefix="/api/v1")
    app.include_router(decisions_router, prefix="/api/v1")
    app.include_router(webhooks_router, prefix="/api/v1")
    app.include_router(experiments_router, prefix="/api/v1")
    app.include_router(audiences_router, prefix="/api/v1")
    app.include_router(platforms_router, prefix="/api/v1")
    app.include_router(ingest_router, prefix="/api/v1")
    app.include_router(referrals_router, prefix="/api/v1")

    logger.info(
        f"UGIE app created | apps={loader.loaded_applications} "
        f"connectors={[c.id for c in connector_registry.list_connectors()]}"
    )
    return app
