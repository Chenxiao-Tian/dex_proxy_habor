from common.constants import ZERO

from gateways.gateway_factory import GatewayFactory

from .strategy import Strategy
from .common.order_manager import (
    OrderManager,
    Side,
    Order,
)
from .common.quoter import Quoter, QuoteDecision
import asyncio


class NaiveMM(Strategy):
    def __init__(
        self,
        config: dict,
    ):
        super().__init__(config)

        self._gateway = GatewayFactory.create(config["gateway"], config)

        self._order_manager = OrderManager(self._gateway)
        self._orders = {}

    async def start(self):
        await super().start()

        await self._gateway.start()

        instruments = [quoter.instrument for quoter in self.quoters.values()]
        await self._order_manager.start(instruments)

        asyncio.create_task(self._run())

    async def _run(self):
        while True:
            for quoter in self.quoters.values():
                orders = [
                    order
                    for order in self._orders.values()
                    if not order.is_finalised()
                    and order.instrument == quoter.instrument
                ]

                qd = await quoter.get_decision()

                bids = [order for order in orders if order.side == Side.BUY]
                self._update_bids(quoter, qd, bids)

                asks = [order for order in orders if order.side == Side.SELL]
                self._update_asks(quoter, qd, asks)

            await asyncio.sleep(2)

    def _update_bids(self, quoter: Quoter, qd: QuoteDecision, bids: list[Order]):
        px, sz, reason = qd.bid_px, qd.bid_sz, qd.bid_sz_reason
        if px.is_nan() or sz <= ZERO:
            self.logger.warning(f"Cancelling all bids: {reason}")
            self._pull_quotes(bids)
            return

        if bids:
            for order in bids:
                if abs(order.price / px - 1) > 0.0001:
                    self.logger.warning(
                        f"Amending order {order.oid} price from {order.price} to {px}"
                    )

                    self._update_quote(order, px, sz)
        else:
            self._insert_quote(quoter.instrument, Side.BUY, px, sz)

    def _update_asks(self, quoter: Quoter, qd: QuoteDecision, asks: list[Order]):
        px, sz, reason = qd.ask_px, qd.ask_sz, qd.ask_sz_reason
        if px.is_nan() or sz <= ZERO:
            self.logger.warning(f"Cancelling all asks: {reason}")
            self._pull_quotes(asks)
            return

        if asks:
            for order in asks:
                if abs(order.price / px - 1) > 0.0001:
                    self.logger.warning(
                        f"Amending order {order.oid} price from {order.price} to {px}"
                    )
                    self._update_quote(order, px, sz)
        else:
            self._insert_quote(quoter.instrument, Side.SELL, px, sz)

    def _insert_quote(self, instrument: str, side: Side, price, qty):
        self.logger.warning(
            f"Inserting quote: iid={instrument}, price={price}, qty={qty}, side={side.name}"
        )

        order = self._order_manager.insert_order(
            instrument,
            side,
            price,
            qty,
        )

        if order.is_finalised():
            return

        self._orders[order.oid] = order
        asyncio.create_task(self._wait_for_order_events(order))

    def _update_quote(self, order: Order, price, qty):
        self._order_manager.cancel_order(order.oid)
        if not order.is_finalised():
            return
        # TODO wait for the order to be cancelled
        self._order_manager.insert_order(order.iid, order.side, price, qty)

        # TODO switch to amend order once it is implemented
        # self._order_manager.amend_order(order.oid, px)

    def _pull_quotes(self, orders: list[Order]):
        for order in orders:
            self._order_manager.cancel_order(order.oid)

    async def _wait_for_order_events(self, order: Order):
        async for event in order:
            self.logger.warning(f"Order event: {event}")

        self.logger.warning(f"Order {order.oid} is done")
        del self._orders[order.oid]

    def get_portfolio_tag(self) -> str:
        return self.config["portfolio_tag"]

    def get_strategy_tag(self) -> str:
        return self.config["strategy_tag"]
