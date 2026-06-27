"""
Inbound Transformer framework.

Converts raw external webhook payloads (Stripe, Paystack, Shopify, …)
into one or more UGIE-compatible event dicts that can be fed directly
to the events API.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class InboundTransformer(ABC):
    """Base class for all inbound webhook → UGIE event transformers."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Unique source identifier (e.g. ``"stripe"``)."""

    @abstractmethod
    def transform(
        self,
        raw_payload: Dict[str, Any],
        platform_id: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """Return a list of EventRequest-compatible dicts."""


class InboundTransformerRegistry:
    """Lookup registry for inbound transformers keyed by source name."""

    def __init__(self):
        self._transformers: Dict[str, InboundTransformer] = {}

    def register(self, transformer: InboundTransformer) -> None:
        self._transformers[transformer.source_name] = transformer

    def get(self, source_name: str) -> Optional[InboundTransformer]:
        return self._transformers.get(source_name)

    def list_sources(self) -> List[str]:
        return sorted(self._transformers.keys())
