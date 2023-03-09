import asyncio
import concurrent
import logging
import weakref
import time
from typing import Callable, Awaitable

import aiohttp
from aiohttp import web, WSCloseCode
from pantheon.utils import receive_json

_logger = logging.getLogger('WebServer')


class WebServer:

    def __init__(self, config, proxy: 'DexProxy'):
        self.__config = config
        self.__proxy = proxy

        self.__app = web.Application()
        self.__app.on_shutdown.append(self.__on_shutdown)
        self.__app.add_routes([web.get('/private/ws', self.__websocket_handler)])

        self.__runner = web.AppRunner(self.__app)

        self.__connections = weakref.WeakSet()

    def register(self, method, path, handler):
        def wrapper(wrapped_handler):
            async def inner(request):
                received_at_ms = int(time.time() * 1000)

                if request.method == 'POST':
                    params = await request.json()
                else:
                    params = request.query
                status, data = await wrapped_handler(request.path, params, received_at_ms)
                _logger.debug(f'status={status}, data={data}')
                return web.json_response(data=data, status=status)

            return inner

        self.__app.add_routes([web.route(method, path, wrapper(handler))])

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
        _logger.debug(f'New client(connection_id={id(ws)}) from {request.remote}')

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
