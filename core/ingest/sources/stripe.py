"""
Stripe inbound transformer.

Maps Stripe webhook events to UGIE event dicts.
Reference: https://docs.stripe.com/api/events/types
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.ingest.transformer import InboundTransformer

_STRIPE_MAP = {
    "payment_intent.succeeded": "PAYMENT_COMPLETED",
    "payment_intent.payment_failed": "PAYMENT_FAILED",
    "customer.subscription.created": "SUBSCRIPTION_STARTED",
    "customer.subscription.deleted": "SUBSCRIPTION_CANCELLED",
    "customer.subscription.updated": "CUSTOM",
    "charge.refunded": "REFUND_COMPLETED",
    "invoice.paid": "PAYMENT_COMPLETED",
    "invoice.payment_failed": "PAYMENT_FAILED",
    "customer.created": "USER_REGISTERED",
    "checkout.session.completed": "ORDER_COMPLETED",
}

_STRIPE_CUSTOM_TYPES = {
    "customer.subscription.updated": "subscription_updated",
}


class StripeTransformer(InboundTransformer):

    @property
    def source_name(self) -> str:
        return "stripe"

    def transform(
        self,
        raw_payload: Dict[str, Any],
        platform_id: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        event_type_str = raw_payload.get("type", "")
        data_obj = raw_payload.get("data", {}).get("object", {})

        ugie_type = _STRIPE_MAP.get(event_type_str, "CUSTOM")
        custom_type = _STRIPE_CUSTOM_TYPES.get(event_type_str)
        if ugie_type == "CUSTOM" and custom_type is None:
            custom_type = f"stripe.{event_type_str}"

        actor_id = (
            data_obj.get("customer")
            or data_obj.get("id")
            or raw_payload.get("id", "unknown")
        )

        properties: Dict[str, Any] = {
            "stripe_event_id": raw_payload.get("id"),
            "stripe_event_type": event_type_str,
        }
        if "amount" in data_obj:
            properties["amount"] = data_obj["amount"]
        if "currency" in data_obj:
            properties["currency"] = data_obj["currency"]
        if "status" in data_obj:
            properties["stripe_status"] = data_obj["status"]
        if "description" in data_obj:
            properties["description"] = data_obj["description"]

        if ugie_type == "PAYMENT_COMPLETED" or ugie_type == "PAYMENT_FAILED":
            properties.setdefault("amount", 0)
            properties.setdefault("currency", "usd")
            if ugie_type == "PAYMENT_FAILED":
                properties.setdefault("reason", data_obj.get("last_payment_error", {}).get("message", "payment_failed"))
        elif ugie_type == "SUBSCRIPTION_STARTED" or ugie_type == "SUBSCRIPTION_CANCELLED":
            plan = data_obj.get("plan", {})
            properties.setdefault("plan_id", plan.get("id", data_obj.get("id", "unknown")))
            if ugie_type == "SUBSCRIPTION_CANCELLED":
                properties.setdefault("reason", data_obj.get("cancellation_details", {}).get("reason", "cancelled"))
        elif ugie_type == "REFUND_COMPLETED":
            properties.setdefault("amount", 0)
            properties.setdefault("currency", "usd")
        elif ugie_type == "ORDER_COMPLETED":
            properties.setdefault("order_id", data_obj.get("id", "unknown"))

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
