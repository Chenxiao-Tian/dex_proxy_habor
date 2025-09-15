import concurrent
import json
import logging
import time
import weakref
from typing import Callable, Awaitable, Optional, Type, List, Dict, Any

import ujson
from aiohttp import web, WSCloseCode
from fastopenapi.routers import AioHttpRouter
from pantheon.utils import receive_json
from pydantic import BaseModel

from .utils import json_type_formatter

from py_dex_common.web_server.dexproxy_aiohtttp_router import DexProxyAioHttpRouter
from py_dex_common.web_server.error_handling import DexProxyGenericAPIError

_logger = logging.getLogger('WebServer')


class WebServer:

    def __init__(self, config, proxy: 'DexProxy', name: str = "Undefined"):
        self.__config = config
        self.__proxy = proxy
        self.__name = name
        self.__app = web.Application()

        self.__router = DexProxyAioHttpRouter(
            app=self.__app,
            title=f"DEX Proxy for '{name}'",
            version=f"1.0.6",
            description=f"OpenAPI documentation for '{name}'"
        )
        self.__app.on_shutdown.append(self.__on_shutdown)
        self.__app.add_routes(
            [web.get('/private/ws', self.__websocket_handler)])

        self.__runner = web.AppRunner(self.__app)

        self.__connections = weakref.WeakSet()

        self.__request_id: int = 0

        self.__route_registry = {}

    def __get_next_request_id(self) -> int:
        self.__request_id += 1
        return self.__request_id

    @property
    def app(self):
        return self.__app

    def register(
            self,
            method: str,
            path: str,
            handler: Callable[[str, Dict[str, Any], int], Awaitable[tuple[int, Dict[str, Any]]]],
            *,
            request_model: Optional[Type[BaseModel]] = None,
            response_model: Optional[Type[BaseModel]] = None,
            response_errors: Optional[Dict[int, Type[BaseModel]]] = None,
            summary: Optional[str] = None,
            tags: Optional[List[str]] = None,
            oapi_in: Optional[List[str]] = None,
    ) -> None:

        use_openapi = (
                oapi_in is not None
                and self.__name in oapi_in
                and response_model is not None
        )

        if use_openapi:
            async def _common(params: dict):
                try:
                    request_id = self.__get_next_request_id()
                    received_at_ms = int(time.time() * 1000)
                    _logger.debug(
                        f'oapi [{request_id}] received_at_ms={received_at_ms}, '
                        f'path={path}, params={params}'
                    )

                    status, data = await handler(path, params, received_at_ms)
                    _logger.debug(f'[{request_id}] status={status}, data={data}')

                    if status != 200:
                        if isinstance(data, BaseModel):
                            raise DexProxyGenericAPIError(data, status)
                        else:
                            try:
                                ujson.dumps(data)
                                safe = data
                            except Exception as e:
                                _logger.exception(f'[{request_id}] status={status}, data={str(data)}')
                                safe = {"message": str(data)}

                            raise DexProxyGenericAPIError(safe, status)

                    if isinstance(data, BaseModel):
                        model = data
                    else:
                        model = response_model(**data)

                    model_json = model.model_dump(mode="json")
                except Exception as e:
                    _logger.exception("Error occurred during request handling")
                    raise e
                return model_json

            decorator_args: Dict[str, Any] = {
                "request_body": request_model,
                "response_model": response_model,
                "status_code": 200,
                "tags": tags or [],
            }
            if response_errors:
                decorator_args["response_errors"] = {
                    code: {"model": mdl} for code, mdl in response_errors.items()
                }

            if request_model is not None:
                async def endpoint(body: request_model):
                    return await _common(body.model_dump(by_alias=True))
            else:
                async def endpoint():
                    return await _common({})

            if summary:
                endpoint.__doc__ = summary

            getattr(self.__router, method.lower())(path, **decorator_args)(endpoint)
            return

        def wrapper(wrapped):
            async def inner(request: web.Request):
                if (method, path) not in self.__route_registry:
                    return web.json_response(
                        data={
                            "error_code": "NOT_FOUND",
                            "error_message": f"Resource not found or request is invalid.",
                        },
                        status=400,
                    )
                received_at_ms = int(time.time() * 1000)
                request_id = self.__get_next_request_id()

                try:
                    if request.method == 'POST':
                        raw_request = await request.text()
                        # This was changed to json.loads so that an empty body is a valid empty dict for the pydantic validator
                        params = ujson.loads(raw_request) if raw_request else {}
                    else:
                        params = dict(request.query)
                    _logger.debug(
                        f'[{request_id}] received_at_ms={received_at_ms}, remote={request.remote}, method={request.method}, path={request.path}, params={params}')
                except Exception as e:
                    _logger.error(
                        f'[{request_id}] error=Malformed JSON, received_at_ms={received_at_ms}, remote={request.remote}, method={request.method}, path={request.path}, raw_request={raw_request}')
                    return web.json_response(data={
                        "error": f"Unable to parse request payload as JSON. payload={raw_request}, parsing_error={e}"},
                                             status=400)

                try:
                    status, data = await wrapped(request.path, params, received_at_ms)
                except ValueError as e:
                    _logger.error(
                        f"[{request_id}] error=Invalid request, message={e}, received_at_ms={received_at_ms}, remote={request.remote}, method={request.method}, path={request.path}, params={params}"
                    )
                    return web.json_response(
                        data={
                            "error_code": "INVALID_REQUEST",
                            "error_message": f"Invalid request. error={e}",
                        },
                        status=400,
                    )
                except Exception as e:
                    _logger.exception("uncatched exception in handler", exc_info=e)
                    status = 500
                    data = {
                        "error_code": "INTERNAL_SERVER_ERROR",
                        "error_message": str(e),
                    }

                _logger.debug(f'[{request_id}] status={status}, data={data}')
                return web.json_response(data=data, status=status,
                                         dumps=lambda x: json.dumps(x, default=json_type_formatter))

            return inner

        for route in self.__app.router.routes():
            assert not (
                    route.method == method and str(route.resource) == path
            ), f"[WebServer] duplicate route: {method} {path}"

        self.__route_registry[(method, path)] = handler
        self.__app.add_routes([web.route(method, path, wrapper(handler))])

    def deregister(self, method, path):
        """Deregister the handler by removing it from the internal registry."""
        if (method, path) in self.__route_registry:
            del self.__route_registry[(method, path)]
            _logger.info(f"Deregistered route {method} {path}")
        else:
            _logger.warning(f"Tried to deregister unknown route {method} {path}")

    async def start(self):
        _logger.info('Starting')
        await self.__runner.setup()

        self.__site = web.TCPSite(self.__runner, port=self.__config['port'])
        await self.__site.start()
        _logger.info('Started')

    async def stop(self):
        _logger.info('Stopping')
        await self.__runner.cleanup()
        _logger.info('Stopped')

    async def send_json(self, ws, msg):
        # if ws is None, broadcast the msg to all clients
        if ws is None:
            connections = self.__connections.copy()
            for ws in connections:
                await self.__send(ws, msg)
        else:
            if ws not in self.__connections:
                return
            await self.__send(ws, msg)

    async def __send(self, ws, msg):
        try:
            _logger.debug(f'Sending {msg}')
            await ws.send_json(msg)
        except Exception as e:
            _logger.exception(f'Could not send {msg}')
            await ws.close()

    async def __on_shutdown(self, app):
        for ws in self.__connections:
            await ws.close(code=WSCloseCode.GOING_AWAY, message='Server shutdown')

    async def __websocket_handler(self, request):

        ws = web.WebSocketResponse()
        _logger.debug(
            f'New client(connection_id={id(ws)}) from {request.remote}')

        await ws.prepare(request)

        self.__connections.add(ws)

        await self.__proxy.on_new_connection(ws)

        while True:
            try:
                msg = await receive_json(ws)
                _logger.debug(f'Received {msg}')

                await self.__proxy.on_message(ws, msg)
            except concurrent.futures.CancelledError:
                pass  # quietly
            except Exception as e:
                _logger.exception(f'Client(connection_id={id(ws)}) lost')
                break

        self.__connections.discard(ws)
