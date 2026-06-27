"""
Meta (Facebook) Ads Connector

Dispatches ad campaign actions and syncs custom audiences
via the Meta Marketing API.
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


class MetaAdsConnector(BaseConnector):
    """
    Connector for Meta Marketing API.

    Handles campaign execution and audience syncing.
    Uses env var resolution for tokens: ${META_ACCESS_TOKEN}.
    """

    API_BASE = "https://graph.facebook.com/v19.0"

    def __init__(
        self,
        access_token: str = "${META_ACCESS_TOKEN}",
        ad_account_id: str = "${META_AD_ACCOUNT_ID}",
        timeout_seconds: float = 30.0,
    ):
        self._access_token = access_token
        self._ad_account_id = ad_account_id
        self._timeout = timeout_seconds

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            id="meta_ads",
            name="Meta Ads Connector",
            description="Facebook/Instagram ad campaigns and custom audiences",
            supported_action_types=["RUN_META_CAMPAIGN", "SYNC_META_AUDIENCE"],
        )

    def execute(self, action: Action) -> ActionResult:
        t0 = time.time()
        try:
            token = _resolve_env_vars(self._access_token)
            account_id = _resolve_env_vars(self._ad_account_id)

            payload = dict(action.payload)
            payload["access_token"] = token

            url = f"{self.API_BASE}/act_{account_id}/campaigns"
            if action.action_type == "SYNC_META_AUDIENCE":
                url = f"{self.API_BASE}/act_{account_id}/customaudiences"

            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(url, json=payload)

            duration_ms = (time.time() - t0) * 1000
            body = self._safe_json(response)

            if response.status_code >= 400:
                return self._failure(
                    action,
                    error=f"HTTP {response.status_code} from Meta API",
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
                error=f"Meta API error: {e}",
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
        account_id = _resolve_env_vars(
            config.get("ad_account_id", self._ad_account_id)
        )
        url = f"{self.API_BASE}/act_{account_id}/customaudiences"

        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(
                    url,
                    json={**payload, "access_token": token},
                )
            return self._safe_json(response)
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def _safe_json(response: httpx.Response) -> dict:
        try:
            return response.json()
        except Exception:
            return {"raw_body": response.text[:500]}
