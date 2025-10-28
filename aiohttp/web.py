"""Minimal HTTP server compatible with the subset of :mod:`aiohttp.web` used.

The production project serves requests via :mod:`aiohttp`.  For this kata we
replace it with a self-contained asyncio HTTP server that supports the handful
of features required by the Harbor adapter:

* registering ``GET``/``POST``/``DELETE`` routes with static paths
* returning JSON responses
* shutting down gracefully

The implementation purposefully remains tiny and omits advanced features like
middlewares or streaming bodies, but it is sufficient to exercise the adapter
from curl or the demo scripts exactly like the real service.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional
from urllib.parse import parse_qs


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

    def match(self, method: str, path: str) -> Optional[_Route]:
        for route in self._routes:
            if route.method == method and route.resource == path:
                return route
        return None


class Response:
    def __init__(self, status: int = 200, body: bytes | None = None, headers: Optional[Dict[str, str]] = None) -> None:
        self.status = status
        self.body = body or b""
        self.headers = headers or {}


class Application:
    def __init__(self) -> None:
        self.router = _Router()
        self.on_shutdown: List[Callable[[Any], Awaitable[Any]]] = []

    def add_routes(self, routes: Iterable[_Route]) -> None:
        for route in routes:
            self.router.add_route(route)

    async def _handle_request(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = await reader.readline()
            if not request_line:
                return
            method, target, _version = request_line.decode("latin-1").strip().split()
            headers: Dict[str, str] = {}
            while True:
                line = await reader.readline()
                if line in (b"\r\n", b"\n", b""):
                    break
                key, value = line.decode("latin-1").split(":", 1)
                headers[key.strip().lower()] = value.strip()

            content_length = int(headers.get("content-length", "0"))
            body = await reader.readexactly(content_length) if content_length else b""

            path, _, query_string = target.partition("?")
            query = {
                key: values[-1] if len(values) == 1 else values
                for key, values in parse_qs(query_string, keep_blank_values=True).items()
            }

            request = Request(method=method.upper(), path=path, query=query)
            request._body = body
            request.headers = headers

            route = self.router.match(request.method, request.path)
            if route is None:
                response = json_response({"error": "Not Found"}, status=404)
            else:
                response = await route.handler(request)
                if isinstance(response, dict):
                    response = json_response(response)

            if not isinstance(response, Response):
                response = json_response({"error": "Invalid response type"}, status=500)

            await self._write_response(writer, response)
        except Exception as exc:  # pragma: no cover - defensive guard
            await self._write_response(
                writer,
                json_response({"error": {"message": str(exc)}}, status=500),
            )

    async def _write_response(self, writer: asyncio.StreamWriter, response: Response) -> None:
        reason = _status_reason(response.status)
        writer.write(f"HTTP/1.1 {response.status} {reason}\r\n".encode("latin-1"))
        headers = {"Content-Length": str(len(response.body)), "Connection": "close"}
        headers.update(response.headers)
        for key, value in headers.items():
            writer.write(f"{key}: {value}\r\n".encode("latin-1"))
        writer.write(b"\r\n")
        writer.write(response.body)
        await writer.drain()
        writer.close()
        try:
            await writer.wait_closed()
        except ConnectionError:  # pragma: no cover - depends on platform
            pass


def get(path: str, handler: Callable[..., Awaitable[Any]]) -> _Route:
    return _Route("GET", path, handler)


def route(method: str, path: str, handler: Callable[..., Awaitable[Any]]) -> _Route:
    return _Route(method.upper(), path, handler)


class AppRunner:
    def __init__(self, app: Application) -> None:
        self.app = app
        self._sites: List[TCPSite] = []

    async def setup(self) -> None:
        return None

    async def cleanup(self) -> None:
        for site in list(self._sites):
            await site.stop()
        for callback in self.app.on_shutdown:
            await callback(self.app)


class TCPSite:
    def __init__(self, runner: AppRunner, host: str = "127.0.0.1", port: int = 0) -> None:
        self.runner = runner
        self.host = host
        self.port = port
        self._server: Optional[asyncio.base_events.Server] = None
        runner._sites.append(self)

    async def start(self) -> None:
        self._server = await asyncio.start_server(self.runner.app._handle_request, host=self.host, port=self.port)
        sockets = self._server.sockets or []
        if sockets:
            self.port = sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None


class WebSocketResponse:
    async def prepare(self, request) -> None:  # pragma: no cover - not used in tests
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
    headers: Dict[str, str] | None = None

    async def text(self) -> str:
        return self._body.decode("utf-8") if getattr(self, "_body", None) else ""


def json_response(
    data: Any,
    status: int = 200,
    dumps: Callable[[Any], str] | None = None,
) -> Response:
    serializer = dumps or (lambda payload: json.dumps(payload))
    body = serializer(data)
    return Response(status=status, body=body.encode("utf-8"), headers={"Content-Type": "application/json"})


_STATUS_REASONS = {
    200: "OK",
    400: "Bad Request",
    404: "Not Found",
    500: "Internal Server Error",
}


def _status_reason(status: int) -> str:
    return _STATUS_REASONS.get(status, "OK")
