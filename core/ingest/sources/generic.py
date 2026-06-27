"""
Generic inbound transformer.

Accepts payloads already in near-UGIE format and normalises them.
Falls back for any source that lacks a dedicated transformer.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.ingest.transformer import InboundTransformer


class GenericTransformer(InboundTransformer):

    @property
    def source_name(self) -> str:
        return "generic"

    def transform(
        self,
        raw_payload: Dict[str, Any],
        platform_id: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        event_type = raw_payload.get("event_type") or raw_payload.get("type", "CUSTOM")
        actor_id = (
            raw_payload.get("actor_id")
            or raw_payload.get("user_id")
            or raw_payload.get("customer_id")
            or "unknown"
        )

        from core.events.schema import EventType

        custom_type = None
        try:
            et = EventType(event_type)
            if et == EventType.CUSTOM:
                custom_type = raw_payload.get("custom_type", "generic_custom")
        except ValueError:
            custom_type = event_type
            event_type = "CUSTOM"

        properties = raw_payload.get("properties", {})
        if isinstance(properties, dict) is False:
            properties = {}

        event: Dict[str, Any] = {
            "application_id": platform_id,
            "type": event_type,
            "actor_id": str(actor_id),
            "properties": properties,
            "source": raw_payload.get("source", "webhook"),
        }
        if custom_type:
            event["custom_type"] = custom_type
            event["properties"]["custom_type"] = custom_type
        if raw_payload.get("target_id"):
            event["target_id"] = raw_payload["target_id"]
        if raw_payload.get("target_type"):
            event["target_type"] = raw_payload["target_type"]
        if raw_payload.get("actor_type"):
            event["actor_type"] = raw_payload["actor_type"]
        if raw_payload.get("context"):
            event["context"] = raw_payload["context"]

        return [event]
