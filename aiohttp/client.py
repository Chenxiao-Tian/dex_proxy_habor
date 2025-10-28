"""Lightweight asynchronous HTTP client built on top of ``requests``.

The original code-base depends on :mod:`aiohttp`.  Shipping the full
dependency is outside the scope of this kata, however the Harbor adapter only
relies on a *very* small subset of its API surface.  The implementation below
provides that surface while still performing real HTTP requests so that the
connector can talk to Harbor's stagenet.

The shim wraps :func:`requests.request` inside ``asyncio`` thread executors so
that it can be awaited just like a real ``aiohttp`` call.  Only the features we
need for the adapter (JSON payloads, basic headers, and response text access)
are implemented.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request
"""Stub client session used by the Harbor tests."""
from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class ClientTimeout:
    total: float | None = None


class _ResponseWrapper:
    """Mimic the subset of :class:`aiohttp.ClientResponse` we rely on."""

    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._text = body.decode("utf-8", errors="replace")
class _DummyResponse:
    def __init__(self, status: int = 200, text: str = "") -> None:
        self.status = status
        self._text = text

    async def text(self) -> str:
        return self._text

    async def __aenter__(self) -> "_ResponseWrapper":
    async def __aenter__(self) -> "_DummyResponse":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


class ClientSession:
    """Very small stand-in for :class:`aiohttp.ClientSession`."""

    def __init__(self, timeout: ClientTimeout | None = None) -> None:
        self._timeout = timeout.total if timeout else None
        self._closed = False

    async def close(self) -> None:
        self._closed = True
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
        if self._closed:
            raise RuntimeError("ClientSession is closed")

        loop = asyncio.get_running_loop()

        def _make_request() -> _ResponseWrapper:
            query = urllib_parse.urlencode(params or {})
            if query:
                separator = "&" if "?" in url else "?"
                full_url = f"{url}{separator}{query}"
            else:
                full_url = url

            data: Optional[bytes]
            if json is not None:
                data = json.dumps(json).encode("utf-8")
            else:
                data = None

            request = urllib_request.Request(full_url, data=data, method=method.upper())
            if headers:
                for key, value in headers.items():
                    request.add_header(key, value)
            if data is not None and "Content-Type" not in request.headers:
                request.add_header("Content-Type", "application/json")

            try:
                with urllib_request.urlopen(request, timeout=self._timeout) as resp:
                    body_bytes = resp.read()
                    status = resp.getcode()
            except urllib_error.HTTPError as exc:
                body_bytes = exc.read()
                status = exc.code
            except urllib_error.URLError as exc:  # pragma: no cover - network errors
                raise ConnectionError(exc.reason) from exc

            return _ResponseWrapper(status, body_bytes)

        response = await loop.run_in_executor(None, _make_request)

        yield response
        yield _DummyResponse()
