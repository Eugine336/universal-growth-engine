"""
Platform Registry

In-memory platform store with lookup by id, slug, and API key hash.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .schema import (
    Platform,
    PlatformQuotas,
    PlatformStatus,
    generate_api_key,
    hash_api_key,
)

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}[a-z0-9]$")


class PlatformRegistry:

    def __init__(self):
        self._platforms: Dict[str, Platform] = {}
        self._slug_index: Dict[str, str] = {}
        self._key_index: Dict[str, str] = {}

    def register(
        self,
        name: str,
        slug: str,
        owner_email: str,
        quotas: Optional[PlatformQuotas] = None,
    ) -> tuple[Platform, str]:
        if not _SLUG_RE.match(slug):
            raise ValueError(
                f"Invalid slug '{slug}': must be 3-64 lowercase alphanumeric, "
                "hyphens, or underscores"
            )
        if slug in self._slug_index:
            raise ValueError(f"Slug '{slug}' is already taken")

        raw_key = generate_api_key()
        platform = Platform(
            name=name,
            slug=slug,
            owner_email=owner_email,
            quotas=quotas or PlatformQuotas(),
        )
        platform.set_api_key(raw_key)

        self._platforms[platform.id] = platform
        self._slug_index[slug] = platform.id
        self._key_index[platform.api_key_hash] = platform.id

        logger.info(f"Registered platform '{name}' (slug={slug}, id={platform.id})")
        return platform, raw_key

    def get_by_id(self, platform_id: str) -> Optional[Platform]:
        return self._platforms.get(platform_id)

    def get_by_slug(self, slug: str) -> Optional[Platform]:
        pid = self._slug_index.get(slug)
        return self._platforms.get(pid) if pid else None

    def get_by_api_key(self, raw_key: str) -> Optional[Platform]:
        key_hash = hash_api_key(raw_key)
        pid = self._key_index.get(key_hash)
        return self._platforms.get(pid) if pid else None

    def list_platforms(
        self, status: Optional[PlatformStatus] = None,
    ) -> List[Platform]:
        platforms = list(self._platforms.values())
        if status is not None:
            platforms = [p for p in platforms if p.status == status]
        return platforms

    def update(
        self,
        platform_id: str,
        name: Optional[str] = None,
        owner_email: Optional[str] = None,
        quotas: Optional[PlatformQuotas] = None,
        config_yaml: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> Optional[Platform]:
        platform = self._platforms.get(platform_id)
        if not platform:
            return None
        if name is not None:
            platform.name = name
        if owner_email is not None:
            platform.owner_email = owner_email
        if quotas is not None:
            platform.quotas = quotas
        if config_yaml is not None:
            platform.config_yaml = config_yaml
        if metadata is not None:
            platform.metadata = metadata
        platform.updated_at = datetime.now(timezone.utc)
        return platform

    def deactivate(self, platform_id: str) -> Optional[Platform]:
        platform = self._platforms.get(platform_id)
        if not platform:
            return None
        old_hash = platform.api_key_hash
        platform.status = PlatformStatus.DEACTIVATED
        platform.updated_at = datetime.now(timezone.utc)
        self._key_index.pop(old_hash, None)
        logger.info(f"Deactivated platform {platform_id}")
        return platform

    def suspend(self, platform_id: str) -> Optional[Platform]:
        platform = self._platforms.get(platform_id)
        if not platform:
            return None
        platform.status = PlatformStatus.SUSPENDED
        platform.updated_at = datetime.now(timezone.utc)
        logger.info(f"Suspended platform {platform_id}")
        return platform

    def rotate_api_key(self, platform_id: str) -> Optional[tuple[Platform, str]]:
        platform = self._platforms.get(platform_id)
        if not platform:
            return None
        old_hash = platform.api_key_hash
        self._key_index.pop(old_hash, None)

        new_key = generate_api_key()
        platform.set_api_key(new_key)
        platform.updated_at = datetime.now(timezone.utc)

        self._key_index[platform.api_key_hash] = platform.id
        logger.info(f"Rotated API key for platform {platform_id}")
        return platform, new_key

    def stats(self) -> dict:
        by_status: Dict[str, int] = {}
        for p in self._platforms.values():
            by_status[p.status.value] = by_status.get(p.status.value, 0) + 1
        return {
            "total_platforms": len(self._platforms),
            "by_status": by_status,
        }
