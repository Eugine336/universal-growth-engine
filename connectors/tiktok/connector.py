"""
TikTok Ads Connector

Dispatches ad campaign actions and syncs custom audiences
via the TikTok Business API.
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


class TikTokAdsConnector(BaseConnector):
    """
    Connector for TikTok Business API.

    Handles campaign execution and custom audience syncing.
    Uses env var resolution for tokens: ${TIKTOK_ACCESS_TOKEN}.
    """

    API_BASE = "https://business-api.tiktok.com/open_api/v1.3"

    def __init__(
        self,
        access_token: str = "${TIKTOK_ACCESS_TOKEN}",
        advertiser_id: str = "${TIKTOK_ADVERTISER_ID}",
        timeout_seconds: float = 30.0,
    ):
        self._access_token = access_token
        self._advertiser_id = advertiser_id
        self._timeout = timeout_seconds

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            id="tiktok_ads",
            name="TikTok Ads Connector",
            description="TikTok ad campaigns and custom audiences",
            supported_action_types=["RUN_TIKTOK_CAMPAIGN", "SYNC_TIKTOK_AUDIENCE"],
        )

    def execute(self, action: Action) -> ActionResult:
        t0 = time.time()
        try:
            token = _resolve_env_vars(self._access_token)
            advertiser = _resolve_env_vars(self._advertiser_id)

            headers = {
                "Access-Token": token,
                "Content-Type": "application/json",
            }

            url = f"{self.API_BASE}/campaign/create/"
            if action.action_type == "SYNC_TIKTOK_AUDIENCE":
                url = f"{self.API_BASE}/segment/mapping/"

            payload = dict(action.payload)
            payload.setdefault("advertiser_id", advertiser)

            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(url, json=payload, headers=headers)

            duration_ms = (time.time() - t0) * 1000
            body = self._safe_json(response)

            if response.status_code >= 400:
                return self._failure(
                    action,
                    error=f"HTTP {response.status_code} from TikTok API",
                    response=body,
                    duration_ms=duration_ms,
                )

            return self._success(
                action,
                connector_ref=body.get("data", {}).get("campaign_id"),
                response=body,
                duration_ms=duration_ms,
            )
        except Exception as e:
            return self._failure(
                action,
                error=f"TikTok API error: {e}",
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
        url = f"{self.API_BASE}/segment/mapping/"
        headers = {
            "Access-Token": token,
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
