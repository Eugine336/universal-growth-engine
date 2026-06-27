"""SDK error types."""

from __future__ import annotations

from typing import Any, Dict, Optional


class UGIEError(Exception):
    """Raised when the UGIE API returns an error response."""

    def __init__(
        self,
        message: str,
        status_code: int = 0,
        response_body: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body or {}
