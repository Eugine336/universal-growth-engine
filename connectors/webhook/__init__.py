"""Webhook Connector — generic HTTP POST connector for external integrations."""

from .connector import WebhookConnector
from .transformer import (
    PayloadTransformer,
    PassthroughTransformer,
    SendGridTransformer,
    TwilioSMSTransformer,
    GenericWebhookTransformer,
    TRANSFORMER_REGISTRY,
)

__all__ = [
    "WebhookConnector",
    "PayloadTransformer",
    "PassthroughTransformer",
    "SendGridTransformer",
    "TwilioSMSTransformer",
    "GenericWebhookTransformer",
    "TRANSFORMER_REGISTRY",
]
