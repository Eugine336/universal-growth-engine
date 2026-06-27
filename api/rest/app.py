"""
UGIE REST API

FastAPI application providing HTTP endpoints for the Universal Growth Engine.
Loads domain configs from UGIE_CONFIG_DIR on startup.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI

from core.config.loader import DomainConfigLoader
from core.decision.policy import PolicyRegistry
from core.entity.registry import EntityRegistry
from core.entity.state import EntityStateMachine
from core.events.validator import EventValidator

logger = logging.getLogger(__name__)


def _load_domain_configs(app: FastAPI) -> None:
    config_dir = os.environ.get("UGIE_CONFIG_DIR", "domain/examples")

    registry = EntityRegistry()
    state_machine = EntityStateMachine()
    validator = EventValidator()
    policy_registry = PolicyRegistry()

    loader = DomainConfigLoader(
        entity_registry=registry,
        state_machine=state_machine,
        event_validator=validator,
        policy_registry=policy_registry,
    )
    loader.load_directory(config_dir)

    app.state.entity_registry = registry
    app.state.state_machine = state_machine
    app.state.event_validator = validator
    app.state.policy_registry = policy_registry
    app.state.config_loader = loader

    for app_id in loader.loaded_applications:
        logger.info(f"Application loaded: {app_id}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO)
    logger.info("UGIE starting up")
    _load_domain_configs(app)
    yield
    logger.info("UGIE shutting down")


app = FastAPI(
    title="Universal Growth Engine",
    version="0.1.0",
    description="Event-driven behavioral intelligence engine",
    lifespan=lifespan,
)


@app.get("/api/v1/health")
async def health() -> Dict[str, Any]:
    loader: DomainConfigLoader = app.state.config_loader
    return {
        "status": "healthy",
        "loaded_applications": loader.loaded_applications,
    }
