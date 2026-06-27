"""
Connector Base + Registry

Every external integration (email, push, SMS, Meta Ads, etc.)
is a connector.

Connectors:
- Implement BaseConnector
- Declare which ActionTypes they handle via their manifest
- Execute actions and return ActionResult
- Never know about behavioral profiles or predictions
- Never call each other

The registry maps ActionTypes → connectors.
The orchestrator uses the registry to route actions.

Built-in stub connectors are included for all standard action types.
In production, replace stubs with real implementations.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Type

from .schema import Action, ActionResult, ActionStatus, ConnectorManifest

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base Connector
# ---------------------------------------------------------------------------

class BaseConnector(ABC):
    """
    Abstract base class for all connectors.

    Subclass this to implement real integrations.
    Each connector handles one or more ActionTypes.
    """

    @property
    @abstractmethod
    def manifest(self) -> ConnectorManifest:
        """Return the connector's manifest."""
        pass

    @abstractmethod
    def execute(self, action: Action) -> ActionResult:
        """
        Execute the action. Return an ActionResult.
        Never raise — catch all exceptions and return a failed result.
        """
        pass

    def can_handle(self, action_type: str) -> bool:
        return action_type in self.manifest.supported_action_types

    def _success(
        self,
        action: Action,
        connector_ref: Optional[str] = None,
        response: Optional[dict] = None,
        duration_ms: Optional[float] = None,
    ) -> ActionResult:
        return ActionResult(
            success=True,
            connector_id=self.manifest.id,
            connector_ref=connector_ref,
            response=response or {},
            duration_ms=duration_ms,
        )

    def _failure(
        self,
        action: Action,
        error: str,
        response: Optional[dict] = None,
        duration_ms: Optional[float] = None,
    ) -> ActionResult:
        return ActionResult(
            success=False,
            connector_id=self.manifest.id,
            error=error,
            response=response or {},
            duration_ms=duration_ms,
        )


# ---------------------------------------------------------------------------
# Stub Connectors (replace with real implementations)
# ---------------------------------------------------------------------------

class EmailConnector(BaseConnector):
    """Stub email connector. Replace with SendGrid / Postmark / SES."""

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            id="email",
            name="Email Connector",
            description="Sends transactional and marketing emails",
            supported_action_types=["SEND_EMAIL"],
            requires_channel=True,
        )

    def execute(self, action: Action) -> ActionResult:
        t0 = time.time()
        try:
            template = action.payload.get("template", "default")
            recipient = action.payload.get("recipient") or action.identity_id
            logger.info(
                f"[EmailConnector] Sending '{template}' to {recipient} "
                f"(identity={action.identity_id})"
            )
            # TODO: replace with real email provider call
            return self._success(
                action,
                connector_ref=f"email_{action.id[:8]}",
                response={"template": template, "recipient": recipient},
                duration_ms=(time.time() - t0) * 1000,
            )
        except Exception as e:
            return self._failure(action, str(e), duration_ms=(time.time() - t0) * 1000)


class PushConnector(BaseConnector):
    """Stub push notification connector."""

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            id="push",
            name="Push Notification Connector",
            supported_action_types=["SEND_PUSH"],
        )

    def execute(self, action: Action) -> ActionResult:
        t0 = time.time()
        try:
            logger.info(f"[PushConnector] Push to identity={action.identity_id}")
            return self._success(
                action,
                connector_ref=f"push_{action.id[:8]}",
                duration_ms=(time.time() - t0) * 1000,
            )
        except Exception as e:
            return self._failure(action, str(e))


class SMSConnector(BaseConnector):
    """Stub SMS connector."""

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            id="sms",
            name="SMS Connector",
            supported_action_types=["SEND_SMS"],
        )

    def execute(self, action: Action) -> ActionResult:
        t0 = time.time()
        try:
            logger.info(f"[SMSConnector] SMS to identity={action.identity_id}")
            return self._success(action, duration_ms=(time.time() - t0) * 1000)
        except Exception as e:
            return self._failure(action, str(e))


class WhatsAppConnector(BaseConnector):
    """Stub WhatsApp connector."""

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            id="whatsapp",
            name="WhatsApp Connector",
            supported_action_types=["SEND_WHATSAPP"],
        )

    def execute(self, action: Action) -> ActionResult:
        t0 = time.time()
        try:
            logger.info(f"[WhatsAppConnector] WhatsApp to identity={action.identity_id}")
            return self._success(action, duration_ms=(time.time() - t0) * 1000)
        except Exception as e:
            return self._failure(action, str(e))


class InAppConnector(BaseConnector):
    """Stub in-app notification connector."""

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            id="in_app",
            name="In-App Connector",
            supported_action_types=["SEND_IN_APP", "SHOW_RECOMMENDATION",
                                    "SHOW_DISCOUNT", "SHOW_UPSELL", "SHOW_ONBOARDING"],
        )

    def execute(self, action: Action) -> ActionResult:
        t0 = time.time()
        try:
            logger.info(
                f"[InAppConnector] In-app {action.action_type} "
                f"to identity={action.identity_id}"
            )
            return self._success(action, duration_ms=(time.time() - t0) * 1000)
        except Exception as e:
            return self._failure(action, str(e))


class WorkflowConnector(BaseConnector):
    """Stub workflow/internal action connector."""

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            id="workflow",
            name="Workflow Connector",
            supported_action_types=[
                "START_WORKFLOW", "ESCALATE_SUPPORT", "REQUEST_REVIEW",
                "FLAG_FOR_REVIEW", "TRIGGER_RETENTION", "TRIGGER_REENGAGEMENT",
                "UNLOCK_FEATURE", "CREATE_DISCOUNT", "OFFER_INCENTIVE",
                "NO_ACTION", "DELAY", "SUPPRESS_AD",
            ],
        )

    def execute(self, action: Action) -> ActionResult:
        t0 = time.time()
        try:
            logger.info(
                f"[WorkflowConnector] {action.action_type} "
                f"for identity={action.identity_id}"
            )
            return self._success(action, duration_ms=(time.time() - t0) * 1000)
        except Exception as e:
            return self._failure(action, str(e))


class AdsConnector(BaseConnector):
    """Stub ads connector (Meta, Google, TikTok, LinkedIn)."""

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            id="ads",
            name="Ads Connector",
            supported_action_types=[
                "RUN_META_CAMPAIGN", "RUN_GOOGLE_CAMPAIGN",
                "RUN_TIKTOK_CAMPAIGN", "RUN_LINKEDIN_CAMPAIGN",
            ],
        )

    def execute(self, action: Action) -> ActionResult:
        t0 = time.time()
        try:
            logger.info(
                f"[AdsConnector] {action.action_type} "
                f"for identity={action.identity_id}"
            )
            return self._success(action, duration_ms=(time.time() - t0) * 1000)
        except Exception as e:
            return self._failure(action, str(e))


# ---------------------------------------------------------------------------
# Connector Registry
# ---------------------------------------------------------------------------

class ConnectorRegistry:
    """
    Maps ActionTypes → connectors.

    Usage:
        registry = ConnectorRegistry()
        registry.register(EmailConnector())
        connector = registry.resolve("SEND_EMAIL")
    """

    def __init__(self):
        self._connectors: Dict[str, BaseConnector] = {}
        self._action_map: Dict[str, str] = {}   # action_type → connector_id
        self._seed_defaults()

    def register(self, connector: BaseConnector) -> None:
        manifest = connector.manifest
        if not manifest.enabled:
            logger.info(f"Connector '{manifest.id}' disabled — skipping registration")
            return
        self._connectors[manifest.id] = connector
        for action_type in manifest.supported_action_types:
            self._action_map[action_type] = manifest.id
        logger.info(
            f"Registered connector '{manifest.id}' | "
            f"handles={manifest.supported_action_types}"
        )

    def resolve(self, action_type: str) -> Optional[BaseConnector]:
        """Find the connector that handles this action type."""
        connector_id = self._action_map.get(action_type)
        if not connector_id:
            return None
        return self._connectors.get(connector_id)

    def get(self, connector_id: str) -> Optional[BaseConnector]:
        return self._connectors.get(connector_id)

    def list_connectors(self) -> List[ConnectorManifest]:
        return [c.manifest for c in self._connectors.values()]

    def supported_action_types(self) -> List[str]:
        return list(self._action_map.keys())

    def _seed_defaults(self) -> None:
        """Register all built-in stub connectors."""
        for connector_cls in [
            EmailConnector,
            PushConnector,
            SMSConnector,
            WhatsAppConnector,
            InAppConnector,
            WorkflowConnector,
            AdsConnector,
        ]:
            self.register(connector_cls())
