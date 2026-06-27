"""
Payload Transformers

Convert UGIE's generic Action into provider-specific HTTP payloads.
Each transformer maps to a named key in the config (e.g. transformer: sendgrid).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict

from core.action.schema import Action


class PayloadTransformer(ABC):
    """Transforms a UGIE Action into a provider-specific HTTP payload."""

    @abstractmethod
    def transform(self, action: Action) -> dict:
        pass


class PassthroughTransformer(PayloadTransformer):
    """Sends action.payload as-is."""

    def transform(self, action: Action) -> dict:
        return dict(action.payload)


class SendGridTransformer(PayloadTransformer):
    """Transforms UGIE email action into SendGrid v3 API format."""

    def transform(self, action: Action) -> dict:
        return {
            "personalizations": [
                {
                    "to": [
                        {
                            "email": action.payload.get(
                                "recipient", action.identity_id
                            )
                        }
                    ]
                }
            ],
            "from": {
                "email": action.payload.get("from_email", "noreply@ugie.io")
            },
            "subject": action.payload.get("subject", "Notification"),
            "content": [
                {
                    "type": "text/html",
                    "value": action.payload.get("body", ""),
                }
            ],
            "custom_args": {
                "action_id": action.id,
                "identity_id": action.identity_id,
            },
        }


class TwilioSMSTransformer(PayloadTransformer):
    """Transforms UGIE SMS action into Twilio API format."""

    def transform(self, action: Action) -> dict:
        return {
            "To": action.payload.get("phone", ""),
            "From": action.payload.get("from_phone", ""),
            "Body": action.payload.get("message", ""),
        }


class GenericWebhookTransformer(PayloadTransformer):
    """Wraps action metadata into a standard webhook envelope."""

    def transform(self, action: Action) -> dict:
        return {
            "event": "action_dispatch",
            "action_id": action.id,
            "action_type": action.action_type,
            "identity_id": action.identity_id,
            "application_id": action.application_id,
            "channel": action.channel,
            "payload": action.payload,
            "context": action.context,
            "dispatched_at": datetime.now(timezone.utc).isoformat(),
        }


TRANSFORMER_REGISTRY: Dict[str, PayloadTransformer] = {
    "passthrough": PassthroughTransformer(),
    "sendgrid": SendGridTransformer(),
    "twilio_sms": TwilioSMSTransformer(),
    "generic_webhook": GenericWebhookTransformer(),
}
