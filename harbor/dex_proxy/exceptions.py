from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HarborAPIError(Exception):
    """Exception raised when the Harbor REST API returns an error."""

    status_code: int
    message: str
    request_id: str | None = None
    payload: dict | None = None

    def __str__(self) -> str:  # pragma: no cover - repr convenience
        base = f"Harbor API error (status={self.status_code})"
        if self.request_id:
            base += f" [request_id={self.request_id}]"
        if self.message:
            base += f": {self.message}"
        return base
