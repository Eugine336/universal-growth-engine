"""
Webhook Connector

Generic connector that POSTs action payloads to configured HTTP endpoints.
Works with any external service that accepts JSON over HTTP.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Dict, List, Optional, Set

import httpx

from core.action.connector import BaseConnector
from core.action.schema import Action, ActionResult, ConnectorManifest

from .transformer import (
    TRANSFORMER_REGISTRY,
    GenericWebhookTransformer,
    PayloadTransformer,
)

logger = logging.getLogger(__name__)

_ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


def _resolve_env_vars(value: str) -> str:
    """Replace ${ENV_VAR} placeholders with environment variable values."""
    def _replacer(match: re.Match) -> str:
        var_name = match.group(1)
        return os.environ.get(var_name, match.group(0))
    return _ENV_VAR_PATTERN.sub(_replacer, value)


def _resolve_headers(headers: Dict[str, str]) -> Dict[str, str]:
    return {k: _resolve_env_vars(v) for k, v in headers.items()}


class WebhookConnector(BaseConnector):
    """
    Generic webhook connector that POSTs action payloads to configured endpoints.

    Each instance handles one or more action types and sends them to a single
    webhook URL with configurable headers and payload transformation.
    """

    def __init__(
        self,
        connector_id: str,
        name: str,
        supported_action_types: List[str],
        webhook_url: str,
        headers: Optional[Dict[str, str]] = None,
        transformer: Optional[PayloadTransformer] = None,
        timeout_seconds: float = 30.0,
        retry_on_status_codes: Optional[Set[int]] = None,
    ):
        self._connector_id = connector_id
        self._name = name
        self._supported_action_types = list(supported_action_types)
        self._webhook_url = webhook_url
        self._raw_headers = headers or {}
        self._transformer = transformer or GenericWebhookTransformer()
        self._timeout = timeout_seconds
        self._retry_status_codes = retry_on_status_codes or {429, 500, 502, 503}

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            id=self._connector_id,
            name=self._name,
            description=f"Webhook connector → {self._webhook_url}",
            supported_action_types=self._supported_action_types,
            metadata={
                "webhook_url": self._webhook_url,
                "transformer": type(self._transformer).__name__,
            },
        )

    def execute(self, action: Action) -> ActionResult:
        t0 = time.time()
        resolved_url = _resolve_env_vars(self._webhook_url)
        resolved_headers = _resolve_headers(self._raw_headers)
        resolved_headers.setdefault("Content-Type", "application/json")

        try:
            payload = self._transformer.transform(action)
        except Exception as e:
            return self._failure(
                action,
                error=f"Payload transform failed: {e}",
                duration_ms=(time.time() - t0) * 1000,
            )

        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(
                    resolved_url,
                    json=payload,
                    headers=resolved_headers,
                )

            duration_ms = (time.time() - t0) * 1000
            response_body = self._safe_json(response)

            if response.status_code >= 400:
                error_msg = (
                    f"HTTP {response.status_code} from {resolved_url}"
                )
                logger.warning(
                    f"[WebhookConnector:{self._connector_id}] {error_msg}"
                )
                return self._failure(
                    action,
                    error=error_msg,
                    response=response_body,
                    duration_ms=duration_ms,
                )

            connector_ref = response_body.get("id") or response_body.get(
                "message_id"
            )

            logger.info(
                f"[WebhookConnector:{self._connector_id}] "
                f"POST {resolved_url} → {response.status_code} "
                f"({duration_ms:.0f}ms)"
            )
            return self._success(
                action,
                connector_ref=str(connector_ref) if connector_ref else None,
                response=response_body,
                duration_ms=duration_ms,
            )

        except httpx.TimeoutException:
            return self._failure(
                action,
                error=f"Timeout after {self._timeout}s to {resolved_url}",
                duration_ms=(time.time() - t0) * 1000,
            )
        except httpx.ConnectError as e:
            return self._failure(
                action,
                error=f"Connection failed to {resolved_url}: {e}",
                duration_ms=(time.time() - t0) * 1000,
            )
        except Exception as e:
            return self._failure(
                action,
                error=f"Unexpected error: {e}",
                duration_ms=(time.time() - t0) * 1000,
            )

    @staticmethod
    def _safe_json(response: httpx.Response) -> dict:
        try:
            return response.json()
        except Exception:
            return {"raw_body": response.text[:500]}
