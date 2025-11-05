"""Minimal subset of :mod:`aiohttp.web` used by the tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional


class Response:
    def __init__(self, *, status: int = 200, body: bytes | None = None, headers: Optional[Dict[str, str]] = None) -> None:
        self.status = status
        self.body = body or b""
        self.headers = headers or {}


def json_response(data: Dict[str, Any], status: int = 200) -> Response:
    import json

    return Response(status=status, body=json.dumps(data).encode("utf-8"), headers={"Content-Type": "application/json"})


class Application:
    def __init__(self) -> None:
        self.router = _Router()
        self.on_shutdown: List[Callable[[Any], Awaitable[Any]]] = []

    def add_routes(self, routes: Iterable["_Route"]) -> None:
        for route in routes:
            self.router.add_route(route)


@dataclass
class _Route:
    method: str
    resource: str
    handler: Callable[..., Awaitable[Any]]


class _Router:
    def __init__(self) -> None:
        self._routes: List[_Route] = []

    def add_route(self, route: _Route) -> None:
        self._routes.append(route)

    def routes(self) -> Iterable[_Route]:  # pragma: no cover - convenience
        return list(self._routes)


def route(method: str, path: str, handler: Callable[..., Awaitable[Any]]) -> _Route:
    return _Route(method.upper(), path, handler)


def get(path: str, handler: Callable[..., Awaitable[Any]]) -> _Route:
    return route("GET", path, handler)


class AppRunner:
    def __init__(self, app: Application) -> None:
        self.app = app

    async def setup(self) -> None:  # pragma: no cover - stub
        return None

    async def cleanup(self) -> None:  # pragma: no cover - stub
        return None


class TCPSite:
    def __init__(self, runner: AppRunner, host: str = "127.0.0.1", port: int = 0) -> None:
        self.runner = runner
        self.host = host
        self.port = port

    async def start(self) -> None:  # pragma: no cover - stub
        return None

    async def stop(self) -> None:  # pragma: no cover - stub
        return None


class WebSocketResponse:  # pragma: no cover - not used in tests
    async def prepare(self, request) -> None:
        return None

    async def close(self, *, message: Optional[str] = None) -> None:
        return None

    async def send_json(self, payload: Any) -> None:
        return None


def run_app(app: Application, *, host: str = "0.0.0.0", port: int = 0) -> None:  # pragma: no cover - not used
    raise RuntimeError("aiohttp.web.run_app is not available in the test stub")
