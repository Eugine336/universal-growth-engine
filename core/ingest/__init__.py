"""Inbound event transformation — external webhooks → UGIE events."""

from core.ingest.transformer import (
    InboundTransformer,
    InboundTransformerRegistry,
)

__all__ = ["InboundTransformer", "InboundTransformerRegistry"]
