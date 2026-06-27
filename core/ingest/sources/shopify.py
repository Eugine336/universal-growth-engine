"""
Shopify inbound transformer.

Maps Shopify webhook topics to UGIE event dicts.
Reference: https://shopify.dev/docs/api/webhooks
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.ingest.transformer import InboundTransformer

_SHOPIFY_MAP = {
    "orders/create": "ORDER_CREATED",
    "orders/paid": "PAYMENT_COMPLETED",
    "orders/cancelled": "ORDER_CANCELLED",
    "orders/fulfilled": "ORDER_COMPLETED",
    "orders/updated": "CUSTOM",
    "customers/create": "USER_REGISTERED",
    "customers/update": "ENTITY_UPDATED",
    "refunds/create": "REFUND_INITIATED",
    "products/create": "CONTENT_CREATED",
    "products/update": "ENTITY_UPDATED",
    "products/delete": "ENTITY_DELETED",
    "checkouts/create": "CUSTOM",
    "checkouts/update": "CUSTOM",
}

_SHOPIFY_CUSTOM_TYPES = {
    "orders/updated": "order_updated",
    "checkouts/create": "checkout_started",
    "checkouts/update": "checkout_updated",
}


class ShopifyTransformer(InboundTransformer):

    @property
    def source_name(self) -> str:
        return "shopify"

    def transform(
        self,
        raw_payload: Dict[str, Any],
        platform_id: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        topic = ""
        if headers:
            topic = headers.get("x-shopify-topic", headers.get("X-Shopify-Topic", ""))
        if not topic:
            topic = raw_payload.get("topic", "")

        ugie_type = _SHOPIFY_MAP.get(topic, "CUSTOM")
        custom_type = _SHOPIFY_CUSTOM_TYPES.get(topic)
        if ugie_type == "CUSTOM" and custom_type is None:
            custom_type = f"shopify.{topic}" if topic else "shopify.unknown"

        customer = raw_payload.get("customer", {})
        actor_id = (
            customer.get("email")
            or str(customer.get("id", ""))
            or raw_payload.get("email")
            or str(raw_payload.get("id", "unknown"))
        )

        properties: Dict[str, Any] = {
            "shopify_topic": topic,
            "shopify_id": raw_payload.get("id"),
        }
        if "total_price" in raw_payload:
            properties["amount"] = raw_payload["total_price"]
        if "currency" in raw_payload:
            properties["currency"] = raw_payload["currency"]
        if "name" in raw_payload:
            properties["order_name"] = raw_payload["name"]

        if ugie_type == "ORDER_CREATED":
            properties.setdefault("order_id", str(raw_payload.get("id", "unknown")))
            properties.setdefault("amount", 0)
        elif ugie_type == "ORDER_COMPLETED":
            properties.setdefault("order_id", str(raw_payload.get("id", "unknown")))
        elif ugie_type == "PAYMENT_COMPLETED":
            properties.setdefault("amount", 0)
            properties.setdefault("currency", raw_payload.get("currency", "USD"))
        elif ugie_type == "REFUND_INITIATED":
            properties.setdefault("amount", 0)
            properties.setdefault("currency", raw_payload.get("currency", "USD"))

        event: Dict[str, Any] = {
            "application_id": platform_id,
            "type": ugie_type,
            "actor_id": str(actor_id),
            "properties": properties,
            "source": "webhook",
        }
        if custom_type:
            event["custom_type"] = custom_type
            event["properties"]["custom_type"] = custom_type

        return [event]
