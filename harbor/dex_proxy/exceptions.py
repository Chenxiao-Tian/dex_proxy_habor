from __future__ import annotations
from typing import Any, Optional


class HarborAPIError(Exception):
    """Raised when a Harbor REST API call fails."""

    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        request_id: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ):
        super().__init__(f"[{status_code}] {message}")
        self.status_code = status_code
        self.message = message
        self.request_id = request_id
        self.payload = payload or {}

    def __str__(self) -> str:
        base = f"HarborAPIError({self.status_code}): {self.message}"
        if self.request_id:
            base += f" [request_id={self.request_id}]"
        if self.payload:
            base += f" | payload keys={list(self.payload.keys())}"
        return base
