import logging
import asyncio

from dataclasses import dataclass
from enum import Enum
from decimal import Decimal
from typing import AsyncIterator
from typing_extensions import Self
from datetime import datetime, timezone


from common.utils import BroadcastAwaitableVariable
from gateways.gateway import Side

from gateways.gateway import Gateway
from gateways.models import OrderType, OrderInsertResponse


class OrderStatus(Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    CANCELING = "CANCELING"
    CANCEL_FAILED = "CANCEL_FAILED"
    FINALISED = "FINALISED"


@dataclass
class OrderState:
    oid: int
    exch_oid: str
    instrument: str
    side: Side
    status: OrderStatus
    price: Decimal
    qty: Decimal
    exec_qty: Decimal
    rem_qty: Decimal

    def __str__(self):
        return (
            f"OrderState(id={self.oid}, instrument={self.instrument}, side={self.side.name}, price={self.price}, qty={self.qty}, "
            f"status={self.status.value}, exec_qty={self.exec_qty}, rem_qty={self.rem_qty}, exch_oid={self.exch_oid}"
        )


@dataclass
class AmendOperation:
    price: Decimal
    tick: int
    inflight: bool


@dataclass
class OrderExecution:
    oid: int
    instrument: str
    side: Side
    price: Decimal
    qty: Decimal

    def __str__(self):
        return f"OrderExecution(id={self.oid}, instrument={self.instrument}, side={self.side.name}, price={self.price}, qty={self.qty})"


@dataclass
class Order:
    instrument: str
    order_type: OrderType
    oid: int
    side: Side
    price: Decimal
    qty: Decimal
    exchange_order_id: str = None

    def __post_init__(self):
        self.rem_qty = self.qty
        self.exec_qty = Decimal(0)

        self._state = BroadcastAwaitableVariable(init=OrderStatus.PENDING)
        self.created_at = datetime.now().astimezone()
        self.finalised_at = None

        self.cancel_task = None
        self.amend_task = None
        self.amend_operations: list[AmendOperation] = []
        self.events = asyncio.Queue()

        self._updated = False

    def is_finalised(self):
        return self.state == OrderStatus.FINALISED

    @property
    def state(self) -> OrderStatus:
        return self._state.get()

    @state.setter
    def state(self, new_state: OrderStatus):
        cur_state = self.state
        if cur_state == OrderStatus.FINALISED:
            return
        if cur_state == OrderStatus.PENDING and new_state in [
            OrderStatus.PENDING,
            OrderStatus.CANCELING,
            OrderStatus.CANCEL_FAILED,
        ]:
            return
        if cur_state == OrderStatus.ACTIVE and new_state in [
            OrderStatus.PENDING,
            OrderStatus.ACTIVE,
            OrderStatus.CANCEL_FAILED,
        ]:
            return
        if cur_state == OrderStatus.CANCELING and new_state in [
            OrderStatus.PENDING,
            OrderStatus.ACTIVE,
            OrderStatus.CANCELING,
        ]:
            return
        if cur_state == OrderStatus.CANCEL_FAILED and new_state in [
            OrderStatus.PENDING,
            OrderStatus.ACTIVE,
            OrderStatus.CANCEL_FAILED,
        ]:
            return

        self._state.set(new_state)
        if self.state in [OrderStatus.ACTIVE, OrderStatus.FINALISED]:
            if self.state == OrderStatus.FINALISED:
                self.finalised_at = datetime.now().astimezone()
                self.rem_qty = Decimal(0)

        self._updated = True

    def transit_to(self, new_state: OrderStatus):
        self.state = new_state
        if self._updated:
            self._notify_order_status()

    def on_insert_response(self, resp: OrderInsertResponse) -> bool:
        if self.exchange_order_id != resp.order_id:
            self.exchange_order_id = resp.order_id
            self._updated = True

        if resp.exec_qty > self.exec_qty:
            fill_qty = resp.exec_qty - self.exec_qty
            self.events.put_nowait(
                OrderExecution(
                    self.oid, self.instrument, self.side, self.price, fill_qty
                )
            )
            self.exec_qty = resp.exec_qty
            self.rem_qty = self.qty - self.exec_qty
            self._updated = True

        assert self.rem_qty == resp.rem_qty, "Remaining quantity mismatch"

        if self.rem_qty > 0:
            self.state = OrderStatus.ACTIVE
        else:
            self.state = OrderStatus.FINALISED

        if self._updated:
            self._notify_order_status()

    def on_order_update(self, update: dict):
        if self.is_finalised():
            return

        exec_qty = update.get("exec_qty", Decimal(0))
        if exec_qty > self.exec_qty:
            fill_qty = exec_qty - self.exec_qty
            self.events.put_nowait(
                OrderExecution(
                    self.oid, self.instrument, self.side, self.price, fill_qty
                )
            )
            self.exec_qty = exec_qty
            self.rem_qty = self.qty - self.exec_qty
            self._updated = True

        status = update.get("status", "")
        if status == "open":
            self.state = OrderStatus.ACTIVE
        else:
            self.state = OrderStatus.FINALISED

        if self.rem_qty > 0:
            self.state = OrderStatus.ACTIVE
        else:
            self.state = OrderStatus.FINALISED

        if self._updated:
            self._notify_order_status()

    def _notify_order_status(self):
        self.events.put_nowait(
            OrderState(
                self.oid,
                self.exchange_order_id,
                self.instrument,
                self.side,
                self.state,
                self.price,
                self.qty,
                self.exec_qty,
                self.rem_qty,
            )
        )
        self._updated = False

    async def wait_for_states(self, *states):
        return await self._state.get_when_oneof(*states)

    def __aiter__(self) -> AsyncIterator[Self]:
        return self

    async def __anext__(self) -> OrderState | OrderExecution:
        if self.events.empty() and self.state == OrderStatus.FINALISED:
            raise StopAsyncIteration()
        return await self.events.get()

    def __repr__(self):
        return (
            f"Order(id={self.oid}, instrument={self.instrument}, side={self.side}, price={self.price}, qty={self.qty}, "
            f"rem_qty={self.rem_qty}, exec_qty={self.exec_qty}, state={self.state.value})"
        )


class OrderManager:
    def __init__(self, gateway: Gateway):
        self._gateway = gateway
        self.logger = logging.getLogger(self.__class__.__name__)

        self.instruments: list[str] = []
        self.orders: dict[int, Order] = {}

        now = datetime.now().astimezone()
        start = datetime(2023, 11, 23, tzinfo=timezone.utc).astimezone(now.tzinfo)
        self.start_order_id = int(now.timestamp() * 1e6 - start.timestamp() * 1e6)

    async def start(self, instruments: list[str]):
        self.logger.info("Starting, cancelling all open orders")
        self.instrument = instruments

        # Query open orders and cancel them
        orders = []
        for instrument in instruments:
            orders.extend(await self.get_orders(instruments))

        for order in orders:
            if order.status == OrderStatus.FINALISED:
                continue

            if order.oid not in self.orders:
                self.orders[order.oid] = order

            self._cancel_order(order)

        asyncio.create_task(self._resync_orders())

    def insert_order(
        self,
        instrument: str,
        side: Side,
        price: Decimal,
        qty: Decimal,
    ) -> Order:
        oid = self.start_order_id
        self.start_order_id += 1
        order = Order(
            instrument,
            OrderType.Limit,
            oid,
            side,
            price,
            qty,
        )
        self.orders[order.oid] = order

        asyncio.create_task(self._do_insert(order))

        return order

    async def _do_insert(self, order: Order):
        try:
            self.logger.info(f"Inserting order {order}")

            resp = await self._gateway.place_order(
                order.instrument,
                order.side,
                order.order_type,
                order.price,
                order.qty,
                client_order_id=order.oid,
            )

            if resp is not None:
                order.on_insert_response(resp)

        except Exception as e:
            self.logger.error(
                f"Error inserting order {order.oid}: %r", e, exc_info=True
            )
            order.transit_to(OrderStatus.FINALISED)

    def amend_order(self, order_id: int, price: Decimal):
        order = self.orders.get(order_id)
        if order is None:
            self.logger.error(f"Order {order_id} not found to amend")
            return

        if order.state in [
            OrderStatus.CANCELING,
            OrderStatus.CANCEL_FAILED,
            OrderStatus.FINALISED,
        ]:
            self.logger.info(
                f"Not amending order {order_id} in state {order.state.value}"
            )
            return

        if order.cancel_task is not None:
            self.logger.info(
                f"Not amending order {order_id} because a cancel is already scheduled"
            )
            return

        # drop throttled amends
        order.amend_operations = [
            amend_operation
            for amend_operation in order.amend_operations
            if amend_operation.inflight
        ]

        if len(order.amend_operations) > 0:
            inflight_amend = order.amend_operations[-1]
            if price == inflight_amend.price:
                self.logger.info(
                    f"Not amending order {order_id} to the same price {price} as last inflight amend"
                )
                return

        order.amend_operations.append(AmendOperation(price, False))

        if order.amend_task is None:
            order.amend_task = asyncio.create_task(self._do_amend(order))

    async def _do_amend(self, order: Order):
        while len(order.amend_operations) > 0:
            state = await order.wait_for_states(OrderStatus.ACTIVE, OrderStatus.FINALISED)
            if state == OrderStatus.FINALISED:
                self.logger.info(
                    f"Order {order.oid} is already finalised, skip amending"
                )
                break

            amend_operation = order.amend_operations[0]

            try:
                self.logger.info(
                    f"Amending order {order.oid} price to {amend_operation.price}"
                )
                amend_operation.inflight = True
                # TODO
                await self._client.amend_order(order.oid, amend_operation.price)
                amend_operation.inflight = False

                self.logger.info(f"Order {order.oid} is amended")
                order.amend_operations.pop(0)

            except asyncio.CancelledError as e:
                self.logger.info(f"Aborted amending order {order.oid}: %r", e)
                break

            except Exception as e:
                self.logger.error(
                    f"Error amending order {order.oid}: %r", e, exc_info=True
                )
                amend_operation.inflight = False

        order.amend_operations.clear()
        order.amend_task = None

    def cancel_order(self, order_id: int):
        order = self.orders.get(order_id)
        if order is None:
            self.logger.warning(f"Order {order_id} not found to cancel")
            return

        self._cancel_order(order)

    def _cancel_order(self, order: Order):
        if order.state in [
            OrderStatus.CANCELING,
            OrderStatus.CANCEL_FAILED,
            OrderStatus.FINALISED,
        ]:
            self.logger.info(
                f"Not cancelling order {order.oid} in state {order.state.value}"
            )
            return

        if order.cancel_task is not None:
            self.logger.info(
                f"Not cancelling order {order.oid} because a cancel is already scheduled"
            )
            return

        if order.amend_task and not order.amend_task.done():
            order.amend_task.cancel("Cancel requested")

        order.cancel_task = asyncio.create_task(self._do_cancel(order))

    async def _do_cancel(self, order: Order):
        while True:
            try:
                state = await order.wait_for_states(
                    OrderStatus.ACTIVE, OrderStatus.CANCEL_FAILED, OrderStatus.FINALISED
                )

                if state == OrderStatus.FINALISED:
                    self.logger.info(
                        f"Order {order.oid} is already finalised, skip cancelling"
                    )
                    break

                self.logger.info(f"Cancelling order {order.oid}")
                order.transit_to(OrderStatus.CANCELING)

                cancelled = await self._gateway.cancel_order(
                    order.instrument,
                    order.oid,
                    order.exchange_order_id,
                )
                if cancelled:
                    self.logger.info(f"Order {order.oid} is cancelled")
                    order.transit_to(OrderStatus.FINALISED)
                    self.orders.pop(order.oid, None)
                    break
                else:
                    self.logger.info(f"Order {order.oid} is not cancelled")
                    order.transit_to(OrderStatus.CANCEL_FAILED)
                    # TODO query order status to cofirm if it is cancelled

            except Exception as e:
                order.transit_to(OrderStatus.CANCEL_FAILED)
                self.logger.error(
                    f"Error cancelling order {order.oid}: %r, retrying", e
                )

                if "OrderDoesNotExist" in str(e):
                    self.logger.info(f"Order {order.oid} does not exist in the pool")
                    order.transit_to(OrderStatus.FINALISED)
                    break
                else:
                    self.logger.error(
                        f"Error cancelling order {order.oid}: {str(e)}, retrying"
                    )

        order.cancel_task = None

    async def _query_order(self, order_id: int):
        order = self.orders.get(order_id)
        if order is None:
            self.logger.debug(f"Order {order_id} not found to query")
            return

        if order.is_finalised():
            return

        if order.exchange_order_id is None:
            self.logger.debug(f"Order {order_id} has no exchange order id")
            return

        self.logger.info(f"Querying order {order_id}")
        resp = await self._gateway.get_order_status(
            order.instrument, order.oid, order.exchange_order_id
        )
        order.on_order_update(resp)

    async def _on_order_updates(self):
        # TODO
        pass

    async def get_orders(self, instrument: str) -> list[Order]:
        self.logger.debug(f"Getting all {instrument} orders")
        orders = []
        # TODO
        return orders

    async def _resync_orders(self):
        while True:
            # resync orders by order id
            for order in self.orders.values():
                await self._query_order(order.oid)

            # resync orders by instrument id
            for instrument in self.instruments:
                self.logger.info(f"Resyncing {instrument} orders")
                try:
                    orders = await self.get_orders(instrument)

                    for order in orders:
                        if order.state == OrderStatus.FINALISED:
                            continue

                        # When order is given up due to reason like timeout but discovered later
                        if (
                            order.oid not in self.orders
                            and order.state == OrderStatus.ACTIVE
                            and order.sell_qty_remaining > 0
                        ):
                            self.orders[order.oid] = order
                            self._cancel_order(order)

                except Exception as e:
                    self.logger.exception(f"Error resyncing {instrument} orders: %r", e)

            now = datetime.now().astimezone()
            orders = list(self.orders.values())
            for order in orders:
                if order.state == OrderStatus.PENDING:
                    created_time = now - order.created_at
                    if created_time.seconds > 30:
                        self.logger.info(
                            f"Order {order.oid} stuck in {OrderStatus.PENDING.value} for {created_time.seconds}s, gave up"
                        )
                        order.transit_to(OrderStatus.FINALISED)

                if order.state == OrderStatus.FINALISED:
                    finalised_time = now - order.finalised_at
                    if finalised_time.seconds > 30:
                        del self.orders[order.oid]
                        self.logger.debug(f"Removed finalised order {order.oid}")

            # resyncing every two blocks
            await asyncio.sleep(12)
