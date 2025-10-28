"""Stub aiohttp.web module for local testing without network dependencies."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable, List, Optional


class _Route:
    def __init__(self, method: str, path: str, handler: Callable[..., Awaitable[Any]]):
        self.method = method
        self.resource = path
        self.handler = handler


class _Router:
    def __init__(self) -> None:
        self._routes: List[_Route] = []

    def routes(self) -> Iterable[_Route]:
        return list(self._routes)

    def add_route(self, route: _Route) -> None:
        self._routes.append(route)


class Application:
    def __init__(self) -> None:
        self.router = _Router()
        self.on_shutdown: List[Callable[[Any], Awaitable[Any]]] = []

    def add_routes(self, routes: Iterable[_Route]) -> None:
        for route in routes:
            self.router.add_route(route)


def get(path: str, handler: Callable[..., Awaitable[Any]]) -> _Route:
    return _Route("GET", path, handler)


def route(method: str, path: str, handler: Callable[..., Awaitable[Any]]) -> _Route:
    return _Route(method.upper(), path, handler)


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


class WebSocketResponse:
    async def prepare(self, request) -> None:  # pragma: no cover - stub
        return None

    async def close(self, *, message: Optional[str] = None) -> None:  # pragma: no cover - stub
        return None

    async def send_json(self, payload: Any) -> None:  # pragma: no cover - stub
        return None

    def can_prepare(self, request) -> bool:  # pragma: no cover - stub
        return True

    async def receive(self):  # pragma: no cover - stub
        class _Message:
            type = "CLOSE"

        return _Message()


@dataclass
class Request:
    method: str
    path: str
    query: dict
    remote: str = "localhost"

    async def text(self) -> str:
        return ""


def json_response(data: Any, status: int = 200, dumps: Callable[[Any], str] | None = None):  # pragma: no cover - stub
    return {"status": status, "data": data}
