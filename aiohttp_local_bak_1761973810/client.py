"""Minimal stub of :mod:`aiohttp`'s client session for the test environment."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class ClientTimeout:
    total: float | None = None


class _DummyResponse:
    def __init__(self, status: int = 200, body: str = "{}") -> None:
        self.status = status
        self._body = body
        self.headers: Dict[str, str] = {}

    async def json(self) -> Any:
        try:
            return json.loads(self._body or "{}")
        except json.JSONDecodeError:
            return {}

    async def text(self) -> str:
        return self._body

    async def __aenter__(self) -> "_DummyResponse":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class ClientSession:
    """Very small stand-in used by the unit tests."""

    def __init__(self, timeout: ClientTimeout | None = None) -> None:
        self._timeout = timeout.total if timeout else None
        self._closed = False

    async def close(self) -> None:  # pragma: no cover - nothing to clean up
        self._closed = True

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
        if self._closed:
            raise RuntimeError("ClientSession is closed")

        yield _DummyResponse()

    # Convenience wrappers to mirror aiohttp API ---------------------------
    def get(self, url: str, **kwargs):  # pragma: no cover - unused in tests
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs):  # pragma: no cover - unused in tests
        return self.request("POST", url, **kwargs)

    def delete(self, url: str, **kwargs):  # pragma: no cover - unused in tests
        return self.request("DELETE", url, **kwargs)
