import aiohttp
import asyncio
import logging
from decimal import Decimal
from typing import Dict, Tuple

from pantheon import Pantheon
from pantheon.timestamp_ns import TimestampNs
from dex_proxy.drift_api import MarketType, OrderStatus, OrderTrade
from dex_proxy.order_cache import OrderCache
from dex_proxy.drift_utils import (
    full_order_to_dict,
    classify_insert_error,
    has_insert_failed,
    min_without_none,
    max_without_none,
    maybe_add_symbol_for_getting_order_record,
    should_get_order_record,
    should_get_order_action_records,
    should_check_place_transaction,
)

from solana.rpc.async_api import AsyncClient, Signature
from solana.rpc.commitment import Confirmed


class RestOrderStatusSyncer:

    def __init__(self, pantheon: Pantheon, config: dict, user_public_key: str, order_cache: OrderCache, dex):
        self.__logger = logging.getLogger("REST_ORDER_POLLER")
        self.__pantheon = pantheon
        self.__order_cache = order_cache
        self.__user_public_key = user_public_key
        self.__dex = dex
        self.__url = config["url"]
        self.__api_key = config.get("api_key")
        self.__request_timeout_s = config.get("request_timeout_s", 5)

        self.__start_polling_after_insert_s = config["start_polling_after_insert_s"]
        self.__refetch_order_action_records_after_s = config["refetch_order_action_records_after_s"]

        self.__order_records_poll_interval_ms = config["order_records_poll_interval_ms"]
        self.__order_action_records_poll_interval_ms = config["order_action_records_poll_interval_ms"]

        self.__mark_insert_failed_only_after_s = config["mark_insert_failed_only_after_s"]

        self.__finalising_rejected_inserts_poll_interval_ms = config[
            "finalising_rejected_inserts_poll_interval_ms"
        ]
        self.__async_solana_client = AsyncClient(dex._config["url"])

        self.__pending_tasks = set()

    def start(self):
        self.__pantheon.spawn(self.__poll_for_order_records())
        self.__pantheon.spawn(self.__poll_for_order_action_records())
        self.__pantheon.spawn(self.__poll_for_finalising_rejected_inserts())

    async def __poll_for_order_records(self):
        while True:
            try:
                symbol_market_to_min_slot: Dict[Tuple[str, str], int] = {}
                for order in self.__order_cache.get_all_open_orders():
                    if should_get_order_record(order, self.__start_polling_after_insert_s):
                        maybe_add_symbol_for_getting_order_record(
                            symbol_market_to_min_slot=symbol_market_to_min_slot,
                            symbol=order.symbol,
                            market=order.drift_market_type,
                            slot=order.slot,
                        )

                tasks = []
                for symbol_market, min_slot in symbol_market_to_min_slot.items():
                    symbol, market = symbol_market
                    tasks.append(self.__get_order_records(symbol=symbol, market=market, fetch_till_slot=min_slot))

                await asyncio.gather(*tasks)
            except Exception as ex:
                self.__logger.exception("Error while REST polling for order records %r", ex)

            await self.__pantheon.sleep(self.__order_records_poll_interval_ms / 1000)

    async def __poll_for_order_action_records(self):
        while True:
            try:
                tasks = []
                for order in self.__order_cache.get_all_open_orders():
                    if should_get_order_action_records(
                        order, self.__start_polling_after_insert_s, self.__refetch_order_action_records_after_s
                    ):
                        tasks.append(self.__get_order_action_records(drift_order_id=order.drift_order_id))

                await asyncio.gather(*tasks)
            except Exception as ex:
                self.__logger.exception("Error while REST polling for order action records %r", ex)

            await self.__pantheon.sleep(self.__order_action_records_poll_interval_ms / 1000)

    async def __poll_for_finalising_rejected_inserts(self):
        while True:
            await self.__pantheon.sleep(self.__finalising_rejected_inserts_poll_interval_ms / 1000)

            try:
                tasks = []
                for order in self.__order_cache.get_all_open_orders():
                    if should_check_place_transaction(order):
                        tasks.append(
                            self.__check_place_transaction(
                                auros_order_id=order.auros_order_id
                            )
                        )
                await asyncio.gather(*tasks)

            except Exception as ex:
                self.__logger.exception(
                    "Error while REST polling for order transactions %r", ex
                )

    async def __get_order_records_next_page(
        self,
        symbol: str,
        market: MarketType,
        fetch_till_slot: int,
        next_page: str,
        min_seen_slot: int | None,
        max_seen_slot: int | None,
    ):
        # sleep to avoid spamming
        await self.__pantheon.sleep(self.__order_records_poll_interval_ms / 1000)
        await self.__get_order_records(
            symbol=symbol,
            market=market,
            fetch_till_slot=fetch_till_slot,
            params=f"?page={next_page}",
            min_seen_slot=min_seen_slot,
            max_seen_slot=max_seen_slot,
        )

    async def __get_order_records(
        self,
        symbol: str,
        market: MarketType,
        fetch_till_slot: int,
        params: str = "",
        min_seen_slot: int | None = None,
        max_seen_slot: int | None = None,
    ):
        try:
            url = f"{self.__url}/{self.__user_public_key}/orders/{market}/{symbol}{params}"
            timeout = aiohttp.ClientTimeout(total=self.__request_timeout_s)
            headers = None
            if self.__api_key:
                headers = {"X-API-Key": self.__api_key}
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers) as response:
                    data = await response.json()
                    status = response.status
                    self.__logger.debug(f"Got order records for symbol={symbol} market={market}: status={status}, data={data}")
                    if status == 200:
                        assert data["success"] == True, "Invalid order records"
                        for record in data["records"]:
                            slot = await self.__handle_order_record(record)
                            min_seen_slot = min_without_none(min_seen_slot, slot)
                            max_seen_slot = max_without_none(max_seen_slot, slot)

                        # fetch next page if required
                        if min_seen_slot and min_seen_slot >= fetch_till_slot:
                            next_page = data["meta"]["nextPage"]
                            self.__logger.debug(f"Scheduling fetching next page of order records for symbol={symbol} market={market}")
                            task = asyncio.create_task(
                                self.__get_order_records_next_page(
                                    symbol=symbol,
                                    market=market,
                                    fetch_till_slot=fetch_till_slot,
                                    next_page=next_page,
                                    min_seen_slot=min_seen_slot,
                                    max_seen_slot=max_seen_slot,
                                )
                            )
                            self.__pending_tasks.add(task)
                            task.add_done_callback(self.__pending_tasks.discard)

                        self.__finalise_failed_to_insert_orders(
                            symbol=symbol, market=market, min_slot=min_seen_slot, max_slot=max_seen_slot
                        )

        except Exception as ex:
            self.__logger.exception(f"Error while requesting order records for symbol={symbol} market={market}. %r", ex)

    async def __get_order_action_records_next_page(self, drift_order_id: int, next_page: str):
        # sleep to avoid spamming
        await self.__pantheon.sleep(self.__order_action_records_poll_interval_ms / 1000)
        await self.__get_order_action_records(drift_order_id=drift_order_id, params=f"?page={next_page}")

    async def __get_order_action_records(self, drift_order_id: int, params: str = ""):
        try:
            url = f"{self.__url}/{self.__user_public_key}/orders/{drift_order_id}/actions{params}"
            timeout = aiohttp.ClientTimeout(total=self.__request_timeout_s)
            headers = None
            if self.__api_key:
                headers = {"X-API-Key": self.__api_key}
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers) as response:
                    data = await response.json()
                    status = response.status
                    self.__logger.debug(f"Got order action records for drift_order_id={drift_order_id}: status={status}, data={data}")
                    if status == 200:
                        assert data["success"] == True, "Invalid order action records"
                        for record in data["records"]:
                            await self.__handle_order_action_record(record)

                        order = self.__order_cache.get_order_from_drift_order_id(drift_order_id)
                        if order:
                            order.last_order_action_record_poll_success_at = TimestampNs.now()

                            next_page = data["meta"]["nextPage"]
                            if next_page:
                                self.__logger.debug(
                                    f"Scheduling fetching next page of order action records for drift_order_id={drift_order_id}"
                                )
                                task = asyncio.create_task(
                                    self.__get_order_action_records_next_page(drift_order_id=drift_order_id, next_page=next_page)
                                )
                                self.__pending_tasks.add(task)
                                task.add_done_callback(self.__pending_tasks.discard)

        except Exception as ex:
            self.__logger.exception(f"Error while requesting order action records for drift_order_id={drift_order_id}. %r", ex)

    async def __check_place_transaction(self, auros_order_id: int):
        self.__logger.info(f"checking place transaction for order {auros_order_id}")

        order = self.__order_cache.get_order_from_auros_order_id(auros_order_id)
        if not order:
            self.__logger.debug(
                f"No order with auros_order_id {auros_order_id} found. Might be cleared."
            )
            return
        if order.is_finalised():
            self.__logger.debug(f"order {auros_order_id} already finalised")
            return
        if order.place_tx_confirmed:
            self.__logger.debug(
                f"place transaction for order {auros_order_id} already confirmed"
            )
            return

        try:
            transaction = await self.__async_solana_client.get_transaction(
                tx_sig=Signature.from_string(order.place_tx_sig),
                encoding="json",
                commitment=Confirmed,
                max_supported_transaction_version=0,
            )

            if transaction.value is None:
                self.__logger.debug(
                    f"empty transaction.value for transaction {order.place_tx_sig} for order {auros_order_id}, probably because transaction block isn't confirmed yet"
                )
                return

            meta = transaction.value.transaction.meta
            if meta.err is None:
                order.place_tx_confirmed = True
                self.__logger.info(
                    f"place transaction {order.place_tx_sig} for order {auros_order_id} confirmed"
                )
                return

            log_message = " ".join(meta.log_messages) if meta.log_messages else ""
            self.__logger.warning(f"Order rejected on-chain: {full_order_to_dict(order)}, reason: {log_message}.")

            if order.is_finalised():
                return

            order.reason = classify_insert_error(log_message)
            order.status = OrderStatus.REJECTED
            self.__order_cache.on_finalised(auros_order_id)
            await self.__dex._send_order_update(auros_order_id)

        except Exception as ex:
            self.__logger.exception(
                f"failed to check place transaction {order.place_tx_sig} for order {auros_order_id}: %r",
                ex,
            )

    def __finalise_failed_to_insert_orders(self, symbol: str, market: MarketType, min_slot: int | None, max_slot: int | None):
        if not min_slot or not max_slot:
            return

        for order in self.__order_cache.get_all_open_orders():
            try:
                if has_insert_failed(
                    order=order,
                    mark_insert_failed_only_after_s=self.__mark_insert_failed_only_after_s,
                    symbol=symbol,
                    market=market,
                    min_slot=min_slot,
                    max_slot=max_slot,
                ):
                    self.__logger.warning(f"Failed to insert order {full_order_to_dict(order)}. Finalising")
                    order.status = OrderStatus.REJECTED
                    self.__order_cache.on_finalised(order.auros_order_id)

                    task = asyncio.create_task(self.__dex._send_order_update(order.auros_order_id))
                    self.__pending_tasks.add(task)
                    task.add_done_callback(self.__pending_tasks.discard)

            except Exception as ex:
                self.__logger.exception(
                    f"Error handling order with auros_order_id {order.auros_order_id} while checking for if it is a failed insert. %r", ex
                )

    async def __handle_order_record(self, record: dict) -> int | None:
        try:
            drift_user_order_id = record["userOrderId"]
            drift_order_id = record["orderId"]
            slot = record["slot"]

            order = self.__order_cache.get_order_from_drift_user_order_id(drift_user_order_id)
            if not order:
                self.__logger.debug(f"No order with drift_user_order_id {drift_user_order_id} found. Might be cleared.")
            elif slot < order.slot:
                self.__logger.debug(f"Ignoring old order record")
            elif order.drift_order_id is None:
                order.drift_order_id = drift_order_id
                self.__order_cache.add_or_update(order)
                order.last_update = TimestampNs.now()
                await self.__dex._send_order_update(order.auros_order_id)

            return slot

        except Exception as ex:
            self.__logger.exception(f"Error while processing handling order record {record}. %r", ex)

        return None

    async def __handle_order_action_record(self, record: dict):
        try:
            if record["action"] == "place":
                pass
            elif record["action"] == "fill":
                await self.__handle_order_filled_event(record)
            elif record["action"] == "cancel":
                await self.__handle_order_cancelled_event(record)
            elif record["action"] == "trigger":
                pass
            else:
                self.__logger.warning(f"Unknown action for the order action record: {record}")
        except Exception as ex:
            self.__logger.exception(f"Error while processing handling order action record {record}. %r", ex)

    async def __handle_order_filled_event(self, record: dict):
        is_maker = record["maker"] == self.__user_public_key
        is_taker = record["taker"] == self.__user_public_key

        # this happens sometimes
        # TODO: need to check why?
        if not is_maker and not is_taker:
            self.__logger.debug("Not our order fill event")
            return

        if is_maker:
            drift_order_id = int(record["makerOrderId"])
            order_qty = Decimal(record["makerOrderBaseAssetAmount"])
            total_executed_qty = Decimal(record["makerOrderCumulativeBaseAssetAmountFilled"])
        elif is_taker:
            drift_order_id = int(record["takerOrderId"])
            order_qty = Decimal(record["takerOrderBaseAssetAmount"])
            total_executed_qty = Decimal(record["takerOrderCumulativeBaseAssetAmountFilled"])

        order = self.__order_cache.get_order_from_drift_order_id(drift_order_id)
        if not order:
            self.__logger.debug(f"No order with drift_order_id {drift_order_id} found. Might be cleared.")
            return

        slot = record["slot"]
        assert order.slot <= slot, "Unexpected slot"

        trade_id = record["fillRecordId"]
        if trade_id in order.seen_trades_id:
            self.__logger.debug("Ignoring already seen order fill update")
            return

        exec_qty = Decimal(record["baseAssetAmountFilled"])
        exec_price = Decimal(record["quoteAssetAmountFilled"]) / exec_qty
        exch_timestamp = TimestampNs.from_ns_since_epoch(record["ts"] * 10**9)

        is_fully_filled = int(order_qty * order.qty_mult) == int(total_executed_qty * order.qty_mult)

        order.trades.append(
            OrderTrade(
                trade_id=trade_id,
                exec_price=exec_price,
                exec_qty=exec_qty,
                liquidity="Maker" if is_maker else "Taker",
                exch_timestamp=exch_timestamp,
            )
        )
        order.seen_trades_id.add(trade_id)
        order.total_executed_qty = total_executed_qty

        if not order.is_finalised() and is_fully_filled:
            order.status = OrderStatus.EXPIRED
            self.__order_cache.on_finalised(order.auros_order_id)

        order.last_update = TimestampNs.now()

        await self.__dex._send_order_update(order.auros_order_id)

    async def __handle_order_cancelled_event(self, record: dict):
        # doesn't make much sense for cancels but data will be either in maker
        # sub-section or in taker sub-section
        in_maker = record["maker"] == self.__user_public_key
        in_taker = record["taker"] == self.__user_public_key

        # this happens for some orders
        # TODO: need to check why?
        if not in_maker and not in_taker:
            self.__logger.debug("Not our order cancel event")
            return

        if in_maker:
            drift_order_id = int(record["makerOrderId"])
            exec_qty = Decimal(record["makerOrderCumulativeBaseAssetAmountFilled"])
        else:
            drift_order_id = int(record["takerOrderId"])
            exec_qty = Decimal(record["takerOrderCumulativeBaseAssetAmountFilled"])

        order = self.__order_cache.get_order_from_drift_order_id(drift_order_id)
        if not order:
            self.__logger.debug(f"No order with drift_order_id {drift_order_id} found. Might be cleared.")
            return

        if order.is_finalised():
            return

        slot = record["slot"]
        assert order.slot <= slot, "Unexpected slot"

        order.total_executed_qty = exec_qty
        order.status = OrderStatus.CANCELLED
        self.__order_cache.on_finalised(order.auros_order_id)

        order.last_update = TimestampNs.now()

        await self.__dex._send_order_update(order.auros_order_id)
