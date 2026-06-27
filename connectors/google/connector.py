"""
Google Ads Connector

Dispatches ad campaign actions and syncs Customer Match audiences
via the Google Ads API.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

import httpx

from core.action.connector import BaseConnector
from core.action.schema import Action, ActionResult, ConnectorManifest

logger = logging.getLogger(__name__)

_ENV_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


def _resolve_env_vars(value: str) -> str:
    def _replacer(match: re.Match) -> str:
        return os.environ.get(match.group(1), match.group(0))
    return _ENV_VAR_PATTERN.sub(_replacer, value)


class GoogleAdsConnector(BaseConnector):
    """
    Connector for Google Ads API.

    Handles campaign execution and Customer Match audience syncing.
    Uses env var resolution for tokens: ${GOOGLE_ADS_DEVELOPER_TOKEN}.
    """

    API_BASE = "https://googleads.googleapis.com/v16"

    def __init__(
        self,
        developer_token: str = "${GOOGLE_ADS_DEVELOPER_TOKEN}",
        customer_id: str = "${GOOGLE_ADS_CUSTOMER_ID}",
        login_customer_id: str = "${GOOGLE_ADS_LOGIN_CUSTOMER_ID}",
        timeout_seconds: float = 30.0,
    ):
        self._developer_token = developer_token
        self._customer_id = customer_id
        self._login_customer_id = login_customer_id
        self._timeout = timeout_seconds

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            id="google_ads",
            name="Google Ads Connector",
            description="Google Ads campaigns and Customer Match audiences",
            supported_action_types=["RUN_GOOGLE_CAMPAIGN", "SYNC_GOOGLE_AUDIENCE"],
        )

    def execute(self, action: Action) -> ActionResult:
        t0 = time.time()
        try:
            token = _resolve_env_vars(self._developer_token)
            customer = _resolve_env_vars(self._customer_id)

            headers = {
                "developer-token": token,
                "Content-Type": "application/json",
            }

            url = f"{self.API_BASE}/customers/{customer}/campaigns:mutate"
            if action.action_type == "SYNC_GOOGLE_AUDIENCE":
                url = (
                    f"{self.API_BASE}/customers/{customer}"
                    f"/offlineUserDataJobs:create"
                )

            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(
                    url,
                    json=action.payload,
                    headers=headers,
                )

            duration_ms = (time.time() - t0) * 1000
            body = self._safe_json(response)

            if response.status_code >= 400:
                return self._failure(
                    action,
                    error=f"HTTP {response.status_code} from Google Ads API",
                    response=body,
                    duration_ms=duration_ms,
                )

            return self._success(
                action,
                connector_ref=body.get("resourceName"),
                response=body,
                duration_ms=duration_ms,
            )
        except Exception as e:
            return self._failure(
                action,
                error=f"Google Ads API error: {e}",
                duration_ms=(time.time() - t0) * 1000,
            )

    def sync_audience(
        self,
        payload: dict,
        config: Dict[str, Any],
    ) -> dict:
        token = _resolve_env_vars(
            config.get("developer_token", self._developer_token)
        )
        customer = _resolve_env_vars(
            config.get("customer_id", self._customer_id)
        )
        url = (
            f"{self.API_BASE}/customers/{customer}"
            f"/offlineUserDataJobs:create"
        )
        headers = {
            "developer-token": token,
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(url, json=payload, headers=headers)
            return self._safe_json(response)
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def _safe_json(response: httpx.Response) -> dict:
        try:
            return response.json()
        except Exception:
            return {"raw_body": response.text[:500]}
