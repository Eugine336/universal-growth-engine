"""
FastAPI Application Factory

Creates the UGIE FastAPI app with all routes and the full
processing pipeline wired to SQL-backed repositories.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI

from core.storage.database import init_db, get_session
from core.storage.repositories import (
    SqlEntityRepository,
    SqlIdentityGraph,
    SqlBehaviorRepository,
)
from core.events.bus import EventBus
from core.events.validator import EventValidator
from core.events.enricher import EventEnricher
from core.events.router import EventRouter
from core.identity.resolver import IdentityResolver
from core.behavior.builder import BehaviorBuilder
from core.prediction.engine import PredictionEngine
from core.decision.engine import DecisionEngine
from core.action.orchestrator import ActionOrchestrator

logger = logging.getLogger(__name__)


class PipelineState:
    """Holds all pipeline components as app-level singletons."""

    def __init__(self):
        self.event_bus: Optional[EventBus] = None
        self.entity_repo: Optional[SqlEntityRepository] = None
        self.identity_graph: Optional[SqlIdentityGraph] = None
        self.behavior_repo: Optional[SqlBehaviorRepository] = None
        self.identity_resolver: Optional[IdentityResolver] = None
        self.behavior_builder: Optional[BehaviorBuilder] = None
        self.prediction_engine: Optional[PredictionEngine] = None
        self.decision_engine: Optional[DecisionEngine] = None
        self.action_orchestrator: Optional[ActionOrchestrator] = None


pipeline = PipelineState()


def _init_pipeline(db_url: str = "sqlite:///ugie.db") -> None:
    engine = init_db(db_url)
    from sqlalchemy.orm import sessionmaker
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    pipeline.entity_repo = SqlEntityRepository(session_factory)
    pipeline.identity_graph = SqlIdentityGraph(session_factory)
    pipeline.behavior_repo = SqlBehaviorRepository(session_factory)

    pipeline.identity_resolver = IdentityResolver(pipeline.identity_graph)
    pipeline.behavior_builder = BehaviorBuilder()
    pipeline.prediction_engine = PredictionEngine(pipeline.behavior_repo)
    pipeline.decision_engine = DecisionEngine(
        behavior_repo=pipeline.behavior_repo,
        prediction_engine=pipeline.prediction_engine,
    )
    pipeline.action_orchestrator = ActionOrchestrator()

    pipeline.event_bus = EventBus(
        validator=EventValidator(),
        enricher=EventEnricher(),
        router=EventRouter(),
    )
    logger.info("UGIE pipeline initialized")


def create_app(db_url: str = "sqlite:///ugie.db") -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        _init_pipeline(db_url)
        yield

    app = FastAPI(
        title="UGIE — Universal Growth Engine",
        version="0.1.0",
        lifespan=lifespan,
    )

    from .routes import health, events, entities, identities, decisions
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(events.router, prefix="/api/v1")
    app.include_router(entities.router, prefix="/api/v1")
    app.include_router(identities.router, prefix="/api/v1")
    app.include_router(decisions.router, prefix="/api/v1")

    return app
