"""
Identity Resolver

The resolver is called on every incoming event.

Given an event, it:
1. Extracts all available identifiers (email, device_id, OAuth token, etc.)
2. Looks up each identifier in the identity graph
3. If a match is found → returns the existing identity (updated)
4. If no match → creates a new anonymous or identified identity
5. If multiple matches → triggers a merge
6. Stamps the resolved identity_id back onto the event
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from .graph import IdentityGraph
from .merger import IdentityMerger
from .schema import (
    Identity,
    IdentityTouchpoint,
    IdentityStatus,
    TouchpointType,
)

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .cross_platform import CrossPlatformManager

logger = logging.getLogger(__name__)


@dataclass
class ResolutionResult:
    identity: Identity
    created: bool = False         # True if a new identity was created
    merged: bool = False          # True if identities were merged
    touchpoints_added: int = 0


class IdentityResolver:
    """
    Resolves any set of identifiers to a single persistent Identity.

    Usage:
        resolver = IdentityResolver(graph)

        result = resolver.resolve(
            application_id="ucmc",
            entity_id="buyer_001",
            touchpoints=[
                IdentityTouchpoint(type=TouchpointType.EMAIL, value="user@example.com"),
                IdentityTouchpoint(type=TouchpointType.DEVICE_ID, value="device_xyz"),
            ]
        )
        identity = result.identity
    """

    def __init__(
        self,
        graph: IdentityGraph,
        cross_platform_manager: Optional["CrossPlatformManager"] = None,
    ):
        self._graph = graph
        self._merger = IdentityMerger(graph)
        self._cross_platform = cross_platform_manager

    def resolve(
        self,
        application_id: str,
        touchpoints: List[IdentityTouchpoint],
        entity_id: Optional[str] = None,
        traits: Optional[dict] = None,
    ) -> ResolutionResult:
        """
        Resolve a set of touchpoints to a single Identity.

        Steps:
        1. Look up each touchpoint in the graph
        2. Collect all matching identities
        3. Merge if multiple matches found
        4. Create new identity if no match
        5. Add new touchpoints to the resolved identity
        6. Register entity mapping
        """

        # Step 1 — find all matching identities across touchpoints
        matched_ids = self._find_matching_identities(touchpoints)

        created = False
        merged = False
        identity: Optional[Identity] = None

        if not matched_ids:
            # Step 2a — no match, create new identity
            identity = self._create_identity(application_id, touchpoints, entity_id, traits)
            created = True
            logger.info(
                f"New identity created | id={identity.id} app={application_id} "
                f"touchpoints={len(touchpoints)}"
            )

        elif len(matched_ids) == 1:
            # Step 2b — single match, use it
            identity = self._graph.get(matched_ids[0])

        else:
            # Step 2c — multiple matches, merge them all into one
            identity = self._merge_all(matched_ids)
            merged = True
            logger.info(
                f"Identities merged | canonical={identity.id} "
                f"merged_count={len(matched_ids)}"
            )

        # Step 3 — add any new touchpoints
        tp_added = 0
        existing_keys = identity.touchpoint_keys()
        for tp in touchpoints:
            if tp.key() not in existing_keys:
                identity.add_touchpoint(tp)
                tp_added += 1
            else:
                # Touch existing to update last_seen
                for existing_tp in identity.touchpoints:
                    if existing_tp.key() == tp.key():
                        existing_tp.touch()

        # Step 4 — register entity mapping
        if entity_id:
            identity.register_entity(application_id, entity_id)

        # Step 5 — apply traits
        if traits:
            for key, value in traits.items():
                identity.set_trait(key, value)

        # Step 6 — touch and persist
        identity.touch(application_id)
        self._graph.save(identity)

        return ResolutionResult(
            identity=identity,
            created=created,
            merged=merged,
            touchpoints_added=tp_added,
        )

    def resolve_from_event(self, event) -> Optional[ResolutionResult]:
        """
        Convenience method — resolve identity directly from an Event.

        Extracts touchpoints from event context (device, session)
        and the actor_id field.
        """
        touchpoints = []

        # Actor ID as a generic touchpoint
        if event.actor_id and event.actor_type:
            touchpoints.append(IdentityTouchpoint(
                type=TouchpointType.CUSTOM,
                value=f"{event.actor_type}:{event.actor_id}",
                application_id=event.application_id,
            ))

        # Device ID from context
        if event.context and event.context.device and event.context.device.device_id:
            touchpoints.append(IdentityTouchpoint(
                type=TouchpointType.DEVICE_ID,
                value=event.context.device.device_id,
                application_id=event.application_id,
            ))

        # Email from properties
        if "email" in event.properties:
            touchpoints.append(IdentityTouchpoint(
                type=TouchpointType.EMAIL,
                value=event.properties["email"],
                application_id=event.application_id,
            ))

        # Phone from properties
        if "phone" in event.properties:
            touchpoints.append(IdentityTouchpoint(
                type=TouchpointType.PHONE,
                value=event.properties["phone"],
                application_id=event.application_id,
            ))

        if not touchpoints:
            logger.debug(
                f"No touchpoints extractable from event {event.id} — "
                f"skipping identity resolution"
            )
            return None

        result = self.resolve(
            application_id=event.application_id,
            touchpoints=touchpoints,
            entity_id=event.actor_id,
        )

        # Stamp identity_id back onto the event
        event.identity_id = result.identity.id

        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _find_matching_identities(
        self, touchpoints: List[IdentityTouchpoint]
    ) -> List[str]:
        """Return unique non-merged identity IDs matching any touchpoint."""
        matched = {}
        for tp in touchpoints:
            identity = self._graph.find_by_touchpoint(tp)
            if identity and not identity.is_merged():
                matched[identity.id] = True
        return list(matched.keys())

    def _create_identity(
        self,
        application_id: str,
        touchpoints: List[IdentityTouchpoint],
        entity_id: Optional[str],
        traits: Optional[dict],
    ) -> Identity:
        identity = Identity(
            status=IdentityStatus.ANONYMOUS,
            application_ids=[application_id],
        )

        for tp in touchpoints:
            identity.add_touchpoint(tp)

        if entity_id:
            identity.register_entity(application_id, entity_id)

        if traits:
            for key, value in traits.items():
                identity.set_trait(key, value)

        self._graph.save(identity)
        return identity

    def _merge_all(self, identity_ids: List[str]) -> Identity:
        """Merge a list of identity IDs into one canonical identity."""
        # Start with the first two
        result = self._merger.merge(identity_ids[0], identity_ids[1])
        canonical = result.canonical if result else self._graph.get(identity_ids[0])

        # Merge remaining
        for identity_id in identity_ids[2:]:
            result = self._merger.merge(canonical.id, identity_id)
            if result:
                canonical = result.canonical

        return canonical

    def resolve_cross_platform(
        self,
        platform_id: str,
        touchpoints: List[IdentityTouchpoint],
        entity_id: Optional[str] = None,
        traits: Optional[dict] = None,
    ) -> ResolutionResult:
        """
        Resolve touchpoints with cross-platform linking awareness.

        If cross-platform linking is enabled for this platform, the resolver
        will link to existing identities from OTHER platforms that share
        matching touchpoints instead of creating a duplicate.

        If linking is disabled, behavior is identical to resolve().
        """
        if not self._cross_platform or not self._cross_platform.is_linking_enabled(platform_id):
            return self.resolve(
                application_id=platform_id,
                touchpoints=touchpoints,
                entity_id=entity_id,
                traits=traits,
            )

        result = self.resolve(
            application_id=platform_id,
            touchpoints=touchpoints,
            entity_id=entity_id,
            traits=traits,
        )

        if len(result.identity.application_ids) > 1:
            for tp in result.identity.touchpoints:
                if tp.type.value in self._cross_platform.get_platform_config(platform_id).linkable_touchpoint_types:
                    self._cross_platform.record_link(
                        identity_id=result.identity.id,
                        platform_ids=result.identity.application_ids[:],
                        link_type=tp.type.value,
                        link_value=tp.value,
                    )
                    break

        return result
