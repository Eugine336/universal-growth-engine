"""
Platform Authentication Middleware

FastAPI dependency that authenticates requests via X-API-Key header.
When no key is provided, falls back to unauthenticated (local) mode
for backward compatibility with existing routes and tests.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import Depends, HTTPException, Request

from core.platform.schema import Platform, PlatformStatus

logger = logging.getLogger(__name__)


def get_current_platform(request: Request) -> Optional[Platform]:
    api_key = (
        request.headers.get("X-API-Key")
        or _extract_bearer(request.headers.get("Authorization"))
    )
    if not api_key:
        return None

    from api.rest.app import pipeline

    registry = pipeline.platform_registry
    if registry is None:
        return None

    platform = registry.get_by_api_key(api_key)
    if platform is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    if platform.status == PlatformStatus.SUSPENDED:
        raise HTTPException(status_code=403, detail="Platform is suspended")
    if platform.status == PlatformStatus.DEACTIVATED:
        raise HTTPException(status_code=403, detail="Platform is deactivated")

    return platform


def require_platform(
    platform: Optional[Platform] = Depends(get_current_platform),
) -> Platform:
    if platform is None:
        raise HTTPException(
            status_code=401,
            detail="API key required. Pass X-API-Key header.",
        )
    return platform


def _extract_bearer(header: Optional[str]) -> Optional[str]:
    if not header:
        return None
    parts = header.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None
