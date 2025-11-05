import asyncio
import logging
import aiohttp
import json

from aiohttp import ClientWebSocketResponse, WSMessage

from typing import AsyncIterator
from typing_extensions import Self


class WebsocketClient:
    def __init__(self, name, url: str):
        self.logger = logging.getLogger(f"{name}.WS")
        self.url = url
        self._client = aiohttp.ClientSession()
        self._ws: ClientWebSocketResponse = None
        self.request_id = 1

        self.request_handlers = {}

    async def __aenter__(self):
        self.logger.info(f"Connecting to {self.url}")
        self._ws = await self._client.ws_connect(self.url)
        self.logger.info(f"Connected to {self.url}")
        return self

    async def __aexit__(self, exec_type, exec_val, exec_tb):
        self.logger.info("Disconnecting")
        await self._ws.close()

    async def __aiter__(self) -> AsyncIterator[Self]:
        while True:
            try:
                async with self as ws:
                    yield ws
            except Exception as e:
                self.logger.error(f"Connection aborted: %r", e)
                continue

    async def recv(self) -> AsyncIterator:
        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    self.logger.debug(f"Received {data}")

                    if "id" in data:
                        request_id = data["id"]
                        self.logger.debug(
                            f"Request {request_id} received reply: {data}"
                        )
                        handler = self.request_handlers.pop(request_id, None)
                        if handler:
                            handler(data)
                        continue

                    yield data
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    self.logger.error(f"Received error: {msg.data}")
                    # break the receiving loop upon error
                    break
                else:
                    self.logger.info(f"Received unknown msg: {msg.data}")

        except asyncio.CancelledError as e:
            self.logger.warning(f"Websocket connection cancelled: %r", e)
        except asyncio.TimeoutError:
            self.logger.warning(f"Websocket connection timed out")
        except Exception as e:
            self.logger.error(f"Unexpected exception: %r", e)

        self.logger.info("Stop receiving")

    async def subscribe(self, method, params, subscribe_handler):
        await self.__send(method, params, subscribe_handler)

    async def request(self, method, params, timeout=30):
        reply_fut = asyncio.get_running_loop().create_future()

        def request_handler(reply):
            reply_fut.set_result(reply)

        request_id = await self.__send(method, params, request_handler)

        try:
            return await asyncio.wait_for(reply_fut, timeout=timeout)
        except asyncio.TimeoutError as e:
            self.logger.error(f"Request {request_id} timed out")
            raise RuntimeError("Request timed out") from e

    async def __send(self, method, params, request_handler):
        request_id = self.request_id
        self.request_id += 1
        msg = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        self.logger.debug(f"Sending {msg}")
        await self._ws.send_json(msg)
        self.request_handlers[request_id] = request_handler
        return request_id
