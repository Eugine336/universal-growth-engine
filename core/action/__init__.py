"""
UGIE Core — Action Orchestrator

Responsibilities:
- Receive decisions from the decision engine
- Route each decision to the correct connector
- Track execution status and results
- Handle retries on transient failures
- Feed results back into the learning loop (event bus)
- Never execute actions directly — always delegate to connectors

The engine decides. Connectors execute.
The orchestrator is the bridge.
"""

from .schema import (
    Action,
    ActionStatus,
    ActionResult,
    ConnectorManifest,
)
from .connector import BaseConnector, ConnectorRegistry
from .orchestrator import ActionOrchestrator

__all__ = [
    "Action",
    "ActionStatus",
    "ActionResult",
    "ConnectorManifest",
    "BaseConnector",
    "ConnectorRegistry",
    "ActionOrchestrator",
]
