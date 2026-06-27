"""
Paystack inbound transformer.

Maps Paystack webhook events to UGIE event dicts.
Reference: https://paystack.com/docs/payments/webhooks/
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.ingest.transformer import InboundTransformer

_PAYSTACK_MAP = {
    "charge.success": "PAYMENT_COMPLETED",
    "transfer.success": "REFUND_COMPLETED",
    "transfer.failed": "PAYMENT_FAILED",
    "subscription.create": "SUBSCRIPTION_STARTED",
    "subscription.disable": "SUBSCRIPTION_CANCELLED",
    "subscription.not_renew": "SUBSCRIPTION_CANCELLED",
    "invoice.create": "CUSTOM",
    "invoice.update": "CUSTOM",
    "invoice.payment_failed": "PAYMENT_FAILED",
    "paymentrequest.success": "PAYMENT_COMPLETED",
    "refund.processed": "REFUND_COMPLETED",
}

_PAYSTACK_CUSTOM_TYPES = {
    "invoice.create": "invoice_created",
    "invoice.update": "invoice_updated",
}


class PaystackTransformer(InboundTransformer):

    @property
    def source_name(self) -> str:
        return "paystack"

    def transform(
        self,
        raw_payload: Dict[str, Any],
        platform_id: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        event_name = raw_payload.get("event", "")
        data = raw_payload.get("data", {})

        ugie_type = _PAYSTACK_MAP.get(event_name, "CUSTOM")
        custom_type = _PAYSTACK_CUSTOM_TYPES.get(event_name)
        if ugie_type == "CUSTOM" and custom_type is None:
            custom_type = f"paystack.{event_name}"

        customer = data.get("customer", {})
        actor_id = (
            customer.get("email")
            or customer.get("customer_code")
            or str(customer.get("id", ""))
            or data.get("reference", "unknown")
        )

        properties: Dict[str, Any] = {
            "paystack_event": event_name,
            "paystack_reference": data.get("reference"),
        }
        if "amount" in data:
            properties["amount"] = data["amount"]
        if "currency" in data:
            properties["currency"] = data["currency"]
        if "status" in data:
            properties["paystack_status"] = data["status"]
        if "channel" in data:
            properties["payment_channel"] = data["channel"]

        if ugie_type == "PAYMENT_COMPLETED" or ugie_type == "PAYMENT_FAILED":
            properties.setdefault("amount", 0)
            properties.setdefault("currency", "NGN")
            if ugie_type == "PAYMENT_FAILED":
                properties.setdefault("reason", data.get("gateway_response", "payment_failed"))
        elif ugie_type == "SUBSCRIPTION_STARTED" or ugie_type == "SUBSCRIPTION_CANCELLED":
            plan = data.get("plan", {})
            properties.setdefault("plan_id", plan.get("plan_code", data.get("subscription_code", "unknown")))
            if ugie_type == "SUBSCRIPTION_CANCELLED":
                properties.setdefault("reason", "cancelled")
        elif ugie_type == "REFUND_COMPLETED":
            properties.setdefault("amount", 0)
            properties.setdefault("currency", "NGN")

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
