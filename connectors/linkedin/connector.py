"""
LinkedIn Ads Connector

Dispatches ad campaign actions and syncs matched audiences
via the LinkedIn Marketing API.
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


class LinkedInAdsConnector(BaseConnector):
    """
    Connector for LinkedIn Marketing API.

    Handles campaign execution and matched audience syncing.
    Uses env var resolution for tokens: ${LINKEDIN_ACCESS_TOKEN}.
    """

    API_BASE = "https://api.linkedin.com/v2"

    def __init__(
        self,
        access_token: str = "${LINKEDIN_ACCESS_TOKEN}",
        ad_account_id: str = "${LINKEDIN_AD_ACCOUNT_ID}",
        timeout_seconds: float = 30.0,
    ):
        self._access_token = access_token
        self._ad_account_id = ad_account_id
        self._timeout = timeout_seconds

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            id="linkedin_ads",
            name="LinkedIn Ads Connector",
            description="LinkedIn ad campaigns and matched audiences",
            supported_action_types=["RUN_LINKEDIN_CAMPAIGN", "SYNC_LINKEDIN_AUDIENCE"],
        )

    def execute(self, action: Action) -> ActionResult:
        t0 = time.time()
        try:
            token = _resolve_env_vars(self._access_token)

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

            url = f"{self.API_BASE}/adCampaignsV2"
            if action.action_type == "SYNC_LINKEDIN_AUDIENCE":
                url = f"{self.API_BASE}/dmpSegments"

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
                    error=f"HTTP {response.status_code} from LinkedIn API",
                    response=body,
                    duration_ms=duration_ms,
                )

            return self._success(
                action,
                connector_ref=body.get("id"),
                response=body,
                duration_ms=duration_ms,
            )
        except Exception as e:
            return self._failure(
                action,
                error=f"LinkedIn API error: {e}",
                duration_ms=(time.time() - t0) * 1000,
            )

    def sync_audience(
        self,
        payload: dict,
        config: Dict[str, Any],
    ) -> dict:
        token = _resolve_env_vars(
            config.get("access_token", self._access_token)
        )
        url = f"{self.API_BASE}/dmpSegments"
        headers = {
            "Authorization": f"Bearer {token}",
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
