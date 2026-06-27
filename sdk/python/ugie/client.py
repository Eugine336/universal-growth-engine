"""
UGIE Python SDK Client.

Usage::

    from sdk.python.ugie import UGIEClient
    ugie = UGIEClient(api_key="ugie_...", base_url="http://localhost:8000")
    ugie.track("user_1", "signup", {"source": "organic"})
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from sdk.python.ugie.errors import UGIEError
from sdk.python.ugie.shortcuts import EVENT_SHORTCUTS


class UGIEClient:
    """Lightweight HTTP client for the UGIE REST API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "http://localhost:8000",
        platform_slug: str = "",
        timeout: float = 30.0,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.platform_slug = platform_slug
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={"X-API-Key": api_key},
            timeout=timeout,
        )

    def _resolve_event_type(self, event_type: str) -> tuple[str, Optional[str]]:
        """Map a friendly or raw event type string to (EventType, custom_type)."""
        shortcut = EVENT_SHORTCUTS.get(event_type.lower())
        if shortcut:
            return shortcut, None

        from core.events.schema import EventType

        try:
            EventType(event_type)
            return event_type, None
        except ValueError:
            return "CUSTOM", event_type

    def _request(
        self,
        method: str,
        path: str,
        json: Any = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        resp = self._client.request(method, path, json=json, params=params)
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except Exception:
                body = {"raw": resp.text}
            detail = body.get("detail", resp.text)
            raise UGIEError(
                message=str(detail),
                status_code=resp.status_code,
                response_body=body,
            )
        return resp.json()

    def track(
        self,
        actor_id: str,
        event_type: str,
        properties: Optional[Dict[str, Any]] = None,
        *,
        target_id: Optional[str] = None,
        target_type: Optional[str] = None,
        actor_type: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> dict:
        resolved_type, custom_type = self._resolve_event_type(event_type)
        payload: Dict[str, Any] = {
            "application_id": self.platform_slug or "sdk",
            "type": resolved_type,
            "actor_id": actor_id,
            "properties": properties or {},
            "source": "api",
        }
        if custom_type:
            payload["custom_type"] = custom_type
            payload["properties"]["custom_type"] = custom_type
        if target_id:
            payload["target_id"] = target_id
        if target_type:
            payload["target_type"] = target_type
        if actor_type:
            payload["actor_type"] = actor_type
        if context:
            payload["context"] = context
        return self._request("POST", "/api/v1/events", json=payload)

    def track_batch(self, events: List[Dict[str, Any]]) -> list:
        batch = []
        for ev in events:
            resolved_type, custom_type = self._resolve_event_type(
                ev.get("event_type", ev.get("type", "CUSTOM"))
            )
            item: Dict[str, Any] = {
                "application_id": self.platform_slug or "sdk",
                "type": resolved_type,
                "actor_id": ev.get("actor_id", ""),
                "properties": ev.get("properties", {}),
                "source": "api",
            }
            if custom_type:
                item["custom_type"] = custom_type
                item["properties"]["custom_type"] = custom_type
            if ev.get("target_id"):
                item["target_id"] = ev["target_id"]
            if ev.get("target_type"):
                item["target_type"] = ev["target_type"]
            if ev.get("actor_type"):
                item["actor_type"] = ev["actor_type"]
            if ev.get("context"):
                item["context"] = ev["context"]
            batch.append(item)
        return self._request("POST", "/api/v1/events/batch", json=batch)

    def identify(self, actor_id: str, traits: Dict[str, Any]) -> dict:
        return self.track(
            actor_id=actor_id,
            event_type="USER_REGISTERED",
            properties=traits,
        )

    def get_profile(self, identity_id: str) -> dict:
        return self._request("GET", f"/api/v1/identities/{identity_id}/profile")

    def get_decisions(self, identity_id: str) -> dict:
        return self._request("GET", f"/api/v1/decisions/{identity_id}")

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
