import asyncio
import logging
from decimal import Decimal, InvalidOperation
from logging import Logger
from typing import List

from pantheon import Pantheon, TimestampNs
from dex_proxy.drift_connector import (
    DriftConfiguration,
    DriftSubscriber,
)
from dex_proxy.drift_api import OrderStatus, OrderTrade
from dex_proxy.order_cache import OrderCache
from dex_proxy.drift_utils import AccessMode

from solana.rpc.commitment import Confirmed
from solders.pubkey import Pubkey

from driftpy.constants.config import DriftEnv
from driftpy.constants.numeric_constants import (
    BASE_PRECISION,
    QUOTE_PRECISION,
)
from driftpy.events.types import WrappedEvent


class EventSubscribers:

    def __init__(
        self,
        pantheon: Pantheon,
        config: dict,
        env: DriftEnv,
        user_public_key: Pubkey,
        order_cache: OrderCache,
        dex,
    ):
        self.__logger = logging.getLogger("EVENT_SUBSCRIBERS")
        self.__pantheon = pantheon
        self.__event_subscribers: List[DriftSubscriber] = []
        self.__dex = dex
        self.__user_public_key = user_public_key
        self.__send_order_updates_for = asyncio.Queue()

        self.__trades_queue = asyncio.Queue()

        if self.__dex.dex_access_mode == AccessMode.READONLY:
            self.subscribed_events = ("OrderActionRecord",)
        else:
            self.subscribed_events = ("OrderRecord", "OrderActionRecord")

        for name, url in config["urls"].items():
            event_handler = EventHandler(
                logger=self.__logger,
                name=name,
                user_public_key=self.__user_public_key,
                order_cache=order_cache,
                dex=self.__dex,
                updates_queue=self.__send_order_updates_for,
                trades_queue=self.__trades_queue,
            )
            configuration = DriftConfiguration(url=url, env=env)

            subscriber_type = config["type"]
            assert subscriber_type == "polling" or subscriber_type == "websocket", "Invalid event_subscriber type"
            event_subscriber = DriftSubscriber(
                config=configuration, type=subscriber_type
            )

            event_subscriber.add_callback(event_handler.handle_event)

            self.__event_subscribers.append(event_subscriber)

    async def start(self):
        for subscriber in self.__event_subscribers:
            await subscriber.start(
                address=self.__user_public_key,
                event_types=self.subscribed_events,
                commitment=Confirmed,
            )

        if self.__dex.dex_access_mode == AccessMode.READWRITE:
            self.__logger.info("Spawning order update utility")
            self.__pantheon.spawn(self.__send_order_updates())

        if self.__dex.dex_access_mode == AccessMode.READONLY:
            self.__logger.info("Spawning receive trades utility")
            self.__pantheon.spawn(self.__receive_trades())

    async def __send_order_updates(self):
        while True:
            try:
                auros_order_id = await self.__send_order_updates_for.get()
                await self.__dex._send_order_update(auros_order_id)
            except Exception as ex:
                self.__logger.exception("Error sending order update %r", ex)

    async def __receive_trades(self):
        while True:
            try:
                trade = await self.__trades_queue.get()
                self.__logger.info(f"Received trade : {trade}")

                event = {
                    "jsonrpc": "2.0",
                    "method": "subscription",
                    "params": {"channel": "TRADE", "data": trade},
                }
                await self.__dex._event_sink.on_event("TRADE", event)
            except BaseException as ex:
                self.__logger.exception("Error sending trade updates %r", ex)


class EventHandler:

    def __init__(
        self,
        logger: Logger,
        name: str,
        user_public_key: Pubkey,
        order_cache: OrderCache,
        dex,
        updates_queue: asyncio.Queue,
        trades_queue: asyncio.Queue,
    ):
        self._logger = logger.getChild(name)
        self.__user_public_key = user_public_key
        self.__order_cache = order_cache
        self.__dex = dex

        self.__updates_queue = updates_queue
        self.__trades_queue = trades_queue

    def handle_event(self, event: WrappedEvent):
        try:
            self._logger.debug(f"Received event: {event}")
            if event.event_type == "OrderRecord":
                self._handle_order_record(event)
            elif event.event_type == "OrderActionRecord":
                self._handle_order_action_record(event)
            else:
                self._logger.warning(f"Unknown event_Type for event: {event}")
        except Exception as ex:
            self._logger.exception(
                f"Exception while handling event: {event}. Error=%r", ex
            )

    def _handle_order_record(self, event: WrappedEvent):
        if self.__dex.dex_access_mode == AccessMode.READONLY:
            return

        if event.data.user == self.__user_public_key:
            drift_order = event.data.order
            drift_user_order_id = drift_order.user_order_id
            order = self.__order_cache.get_order_from_drift_user_order_id(
                drift_user_order_id
            )
            if not order:
                self._logger.debug(
                    f"No order with drift_user_order_id {drift_user_order_id} found. Might be cleared."
                )
                return

            assert order.slot <= drift_order.slot, "Unexpected slot"

            if order.drift_order_id is None:
                order.drift_order_id = drift_order.order_id
                self.__order_cache.add_or_update(order)
                order.last_update = TimestampNs.now()

                self.__updates_queue.put_nowait(order.auros_order_id)

    def _handle_order_action_record(self, event: WrappedEvent):
        action = str(event.data.action)
        if action == "OrderAction.Place()":
            pass
        elif action == "OrderAction.Fill()":
            self._handle_order_filled_event(event)

            if self.__dex.dex_access_mode == AccessMode.READONLY:
                self._parse_trade_from_order_filled_event(event)
        elif action == "OrderAction.Cancel()":
            self._handle_order_cancelled_event(event)
        elif action == "OrderAction.Trigger()":
            pass
        else:
            self._logger.warning(f"Unhandled order action record: {event}")

    def _safe_format_fee(self, fee, quote_precision):
        try:
            if fee is None:
                return "0"
            value = Decimal(str(fee)) / quote_precision
            return f"{value:f}"
        except (InvalidOperation, ValueError, TypeError):
            return "0"

    def _parse_trade_from_order_filled_event(self, event: WrappedEvent) -> None:
        try:
            self._logger.info(
                f"[_parse_trade_from_order_filled_event]: processing trade event {event}"
            )
            data = event.data
            is_maker = data.maker == self.__user_public_key
            is_taker = data.taker == self.__user_public_key

            if not is_maker and not is_taker:
                self._logger.debug("Not our order fill event")
                return

            order_id = data.taker_order_id if is_taker else data.maker_order_id
            order_direction = (
                data.taker_order_direction if is_taker else data.maker_order_direction
            )
            fee = data.taker_fee if is_taker else data.maker_fee

            base = Decimal(str(data.base_asset_amount_filled))
            quote = Decimal(str(data.quote_asset_amount_filled))

            trade = {
                "exchange_order_id": order_id,
                "exchange_trade_id": str(data.fill_record_id),
                "market_index": data.market_index,
                "exchange_account": str(self.__user_public_key),
                "side": str(order_direction),
                "quantity": f"{base / Decimal(BASE_PRECISION):f}",
                "price": f"{(quote / base) * (10**3):f}",
                "exchange_timestamp": int(data.ts),
                "fee": self._safe_format_fee(fee, QUOTE_PRECISION),
                "fee_ccy": "USDC",
                "liquidity": "TAKER" if is_taker else "MAKER",
                "raw_exchange_message": str(event),
            }

            self.__trades_queue.put_nowait(trade)

        except Exception as e:
            self._logger.error(f"Error processing trade event: {e}", exc_info=True)

    def _handle_order_filled_event(self, event: WrappedEvent):
        if self.__dex.dex_access_mode == AccessMode.READONLY:
            return

        is_maker = event.data.maker == self.__user_public_key
        is_taker = event.data.taker == self.__user_public_key

        # this happens sometimes
        # TODO: need to check why?
        if not is_maker and not is_taker:
            self._logger.debug("Not our order fill event")
            return

        if is_maker:
            drift_order_id = event.data.maker_order_id
            total_executed_qty_scaled = Decimal(
                event.data.maker_order_cumulative_base_asset_amount_filled
            )
            is_fully_filled = (
                event.data.maker_order_base_asset_amount
                == event.data.maker_order_cumulative_base_asset_amount_filled
            )
        elif is_taker:
            drift_order_id = event.data.taker_order_id
            total_executed_qty_scaled = Decimal(
                event.data.taker_order_cumulative_base_asset_amount_filled
            )
            is_fully_filled = (
                event.data.taker_order_base_asset_amount
                == event.data.taker_order_cumulative_base_asset_amount_filled
            )

        order = self.__order_cache.get_order_from_drift_order_id(drift_order_id)
        if not order:
            self._logger.debug(
                f"No order with drift_order_id {drift_order_id} found. Might be cleared."
            )
            return

        slot = event.slot
        assert order.slot <= slot, "Unexpected slot"

        trade_id = str(event.data.fill_record_id)
        if trade_id in order.seen_trades_id:
            self._logger.debug("Ignoring duplicate order fill update")
            return

        qty = Decimal(event.data.base_asset_amount_filled) / order.qty_mult
        price = (Decimal(event.data.quote_asset_amount_filled) / order.price_mult) / qty
        exch_timestamp = TimestampNs.from_ns_since_epoch(event.data.ts * 10**9)

        order.trades.append(
            OrderTrade(
                trade_id=trade_id,
                exec_price=price,
                exec_qty=qty,
                liquidity="Maker" if is_maker else "Taker",
                exch_timestamp=exch_timestamp,
            )
        )
        order.seen_trades_id.add(trade_id)
        order.total_executed_qty = total_executed_qty_scaled / order.qty_mult

        if not order.is_finalised() and is_fully_filled:
            order.status = OrderStatus.EXPIRED
            self.__order_cache.on_finalised(order.auros_order_id)

        order.last_update = TimestampNs.now()

        self.__updates_queue.put_nowait(order.auros_order_id)

    def _handle_order_cancelled_event(self, event: WrappedEvent):
        if self.__dex.dex_access_mode == AccessMode.READONLY:
            return

        # doesn't make much sense for cancels but data will be either in maker
        # sub-section or in taker sub-section
        in_maker = event.data.maker == self.__user_public_key
        in_taker = event.data.taker == self.__user_public_key

        # this happens sometimes
        # TODO: need to check why?
        if not in_maker and not in_taker:
            self._logger.debug("Not our order cancel event")
            return

        if in_maker:
            drift_order_id = event.data.maker_order_id
            quote_asset_amount_filled = Decimal(
                event.data.maker_order_cumulative_base_asset_amount_filled
            )
        else:
            drift_order_id = event.data.taker_order_id
            quote_asset_amount_filled = Decimal(
                event.data.taker_order_cumulative_base_asset_amount_filled
            )

        order = self.__order_cache.get_order_from_drift_order_id(drift_order_id)
        if not order:
            self._logger.debug(f"No order with drift_order_id {drift_order_id} found")
            return

        if order.is_finalised():
            return

        slot = event.slot
        assert order.slot <= slot, "Unexpected slot"

        exec_qty = quote_asset_amount_filled / order.qty_mult
        order.total_executed_qty = exec_qty
        order.status = OrderStatus.CANCELLED
        self.__order_cache.on_finalised(order.auros_order_id)

        order.last_update = TimestampNs.now()

        self.__updates_queue.put_nowait(order.auros_order_id)
