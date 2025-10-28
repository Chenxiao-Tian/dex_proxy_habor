"""Stub client session used by the Harbor tests."""
from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class ClientTimeout:
    total: float | None = None


class _DummyResponse:
    def __init__(self, status: int = 200, text: str = "") -> None:
        self.status = status
        self._text = text

    async def text(self) -> str:
        return self._text

    async def __aenter__(self) -> "_DummyResponse":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class ClientSession:
    def __init__(self, timeout: ClientTimeout | None = None) -> None:
        self.timeout = timeout

    async def close(self) -> None:  # pragma: no cover - nothing to clean up
        return None

    @asynccontextmanager
    async def request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        yield _DummyResponse()
