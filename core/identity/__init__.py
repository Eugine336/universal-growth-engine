"""
UGIE Core — Identity Module

Responsibilities:
- Maintain a persistent identity graph
- Resolve any actor (email, device, OAuth, wallet, API key) to one identity
- Merge identities when the same person is detected across touchpoints
- Expose identity profiles to downstream modules
"""

from .schema import Identity, IdentityTouchpoint, TouchpointType, IdentityStatus
from .resolver import IdentityResolver
from .graph import IdentityGraph
from .merger import IdentityMerger

__all__ = [
    "Identity",
    "IdentityTouchpoint",
    "TouchpointType",
    "IdentityStatus",
    "IdentityResolver",
    "IdentityGraph",
    "IdentityMerger",
]
