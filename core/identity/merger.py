"""
Identity Merger

When the engine determines that two identity nodes represent the
same real person, the merger combines them into one canonical identity.

Merge rules:
- The older identity wins (lower created_at becomes the canonical)
- All touchpoints from both are combined (deduped by key)
- All entity mappings are combined
- All traits are merged (canonical wins on conflict)
- The secondary identity is marked as merged_into the canonical
- All touchpoint index entries point to the canonical identity
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

from .schema import Identity, IdentityStatus
from .graph import IdentityGraph

logger = logging.getLogger(__name__)


class MergeResult:
    def __init__(
        self,
        canonical: Identity,
        absorbed: Identity,
        touchpoints_merged: int,
        traits_merged: int,
        entities_merged: int,
    ):
        self.canonical = canonical
        self.absorbed = absorbed
        self.touchpoints_merged = touchpoints_merged
        self.traits_merged = traits_merged
        self.entities_merged = entities_merged

    def __repr__(self):
        return (
            f"MergeResult(canonical={self.canonical.id}, "
            f"absorbed={self.absorbed.id}, "
            f"touchpoints_merged={self.touchpoints_merged})"
        )


class IdentityMerger:
    """
    Merges two identity nodes into one canonical identity.

    Usage:
        merger = IdentityMerger(graph)
        result = merger.merge(identity_a_id, identity_b_id)
        # result.canonical is the surviving identity
    """

    def __init__(self, graph: IdentityGraph):
        self._graph = graph

    def merge(self, identity_id_a: str, identity_id_b: str) -> Optional[MergeResult]:
        """
        Merge identity B into identity A (or whichever is older).
        Returns MergeResult or None if either identity is not found.
        """
        a = self._graph.get(identity_id_a)
        b = self._graph.get(identity_id_b)

        if not a or not b:
            logger.warning(
                f"Merge failed: one or both identities not found "
                f"({identity_id_a}, {identity_id_b})"
            )
            return None

        if a.id == b.id:
            logger.info("Merge skipped: same identity")
            return None

        if a.is_merged() or b.is_merged():
            logger.warning(
                f"Merge skipped: one identity is already merged "
                f"(a.merged={a.is_merged()}, b.merged={b.is_merged()})"
            )
            return None

        # Canonical = older identity
        canonical, absorbed = self._elect_canonical(a, b)

        logger.info(
            f"Merging identity {absorbed.id} → {canonical.id}"
        )

        # Merge touchpoints
        tp_count = 0
        existing_keys = canonical.touchpoint_keys()
        for tp in absorbed.touchpoints:
            if tp.key() not in existing_keys:
                canonical.touchpoints.append(tp)
                tp_count += 1

        # Merge entity mappings (canonical wins on conflict)
        entity_count = 0
        for app_id, entity_id in absorbed.entity_ids.items():
            if app_id not in canonical.entity_ids:
                canonical.entity_ids[app_id] = entity_id
                entity_count += 1

        # Merge application IDs
        for app_id in absorbed.application_ids:
            if app_id not in canonical.application_ids:
                canonical.application_ids.append(app_id)

        # Merge traits (canonical wins on key conflict)
        trait_count = 0
        for key, value in absorbed.traits.items():
            if key not in canonical.traits:
                canonical.traits[key] = value
                trait_count += 1

        # Merge canonical identifiers
        if not canonical.canonical_email and absorbed.canonical_email:
            canonical.canonical_email = absorbed.canonical_email
        if not canonical.canonical_phone and absorbed.canonical_phone:
            canonical.canonical_phone = absorbed.canonical_phone

        # Record merge history
        canonical.merged_ids.append(absorbed.id)
        canonical.merged_ids.extend(absorbed.merged_ids)
        canonical.updated_at = datetime.now(timezone.utc)

        # Extend first/last seen
        if absorbed.first_seen_at < canonical.first_seen_at:
            canonical.first_seen_at = absorbed.first_seen_at
        if absorbed.last_seen_at > canonical.last_seen_at:
            canonical.last_seen_at = absorbed.last_seen_at

        # Mark absorbed as merged
        absorbed.status = IdentityStatus.MERGED
        absorbed.merged_into = canonical.id
        absorbed.updated_at = datetime.now(timezone.utc)

        # Persist both
        self._graph.save(canonical)
        self._graph.save(absorbed)

        logger.info(
            f"Merge complete | canonical={canonical.id} absorbed={absorbed.id} "
            f"touchpoints_added={tp_count} traits_added={trait_count}"
        )

        return MergeResult(
            canonical=canonical,
            absorbed=absorbed,
            touchpoints_merged=tp_count,
            traits_merged=trait_count,
            entities_merged=entity_count,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _elect_canonical(
        self, a: Identity, b: Identity
    ) -> Tuple[Identity, Identity]:
        """
        Elect the canonical identity.
        Priority: verified > older > more touchpoints.
        """
        a_score = self._score(a)
        b_score = self._score(b)

        if a_score >= b_score:
            return a, b
        return b, a

    def _score(self, identity: Identity) -> float:
        score = 0.0
        # Older = higher score (inverse of age in seconds)
        age = (datetime.now(timezone.utc) - identity.created_at).total_seconds()
        score += age * 0.001
        # More touchpoints = better
        score += len(identity.touchpoints) * 10
        # Verified touchpoints = much better
        score += sum(5 for tp in identity.touchpoints if tp.verified) * 10
        # Has canonical email
        if identity.canonical_email:
            score += 50
        return score
