import asyncio
import logging
import signal
from typing import Optional, Dict

from kuru_sdk import MarketParams
from kuru_sdk.types import OrderCreatedPayload, OrderCancelledPayload, TradePayload
from kuru_sdk.websocket_handler import WebSocketHandler


class OrderTimingInfo:
    pass


class WsOrderManager:

    instances: Dict[str, "WsOrderManager"] = {}

    @classmethod
    async def ensure_instance(cls, market_address: str, ws_url: str, private_key: str, market_params: MarketParams) -> "WsOrderManager":
        if market_address not in cls.instances:
            cls.instances[market_address] = WsOrderManager(market_address, ws_url, private_key, market_params)
            await cls.instances[market_address].initialize()
        return cls.instances[market_address]

    @classmethod
    async def clear_instance(cls, market_address: str):
        if market_address in cls.instances:
            await cls.instances[market_address].shutdown()
            del cls.instances[market_address]

    def __init__(self, market_address: str, ws_url: str, private_key: str, market_params: MarketParams):
        self.market_address = market_address
        self.ws_url = ws_url
        self.private_key = private_key
        self.market_params = market_params

        self._logger =  logging.getLogger(__name__)

    async def on_order_created(self, payload: OrderCreatedPayload):
        self._logger.info("WebSocket OrderCreated event received: %s", payload)

    async def on_order_cancelled(self, payload: OrderCancelledPayload):
        self._logger.info("WebSocket OrderCancelled event received: %s", payload)

    async def on_trade(self, payload: TradePayload):
        # TODO: for some reason Kuru send order_id=0 for IOC orders
        self._logger.info("WebSocket Trade event received: %s", payload)

    async def initialize(self):
        self.shutdown_event = asyncio.Future()

        if self.market_address is None or self.private_key is None or self.ws_url is None:
            raise ValueError("market_address, private_key, and ws_url must be provided")

        self.ws_client = WebSocketHandler(
            websocket_url=self.ws_url,
            market_address=self.market_address,
            market_params=self.market_params,
            on_order_created=self.on_order_created,
            on_order_cancelled=self.on_order_cancelled,
            on_trade=self.on_trade,
        )

        await self.ws_client.connect()

        # Add signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(self.shutdown(s)))

    async def shutdown(self, sig: Optional[int] = None):
        self._logger.info("Received exit signal: %s", sig)
        self._logger.info("Disconnecting client...")
        try:
            await self.ws_client.disconnect()
        except Exception:
            self._logger.exception("Error during disconnect")
        finally:
            self._logger.info("Client disconnected.")
            if self.shutdown_event is not None:
                self.shutdown_event.set_result(True)
            # Optional: Clean up signal handlers
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.remove_signal_handler(sig)
