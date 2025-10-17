import logging
from typing import Dict

from pantheon import Pantheon
from pantheon.timestamp_ns import TimestampNs
from drift_api import Order


class OrderCache:

    def __init__(self, pantheon: Pantheon, config: dict):
        self.__auros_order_id_to_orders: Dict[int, Order] = {}
        self.__drift_user_order_id_2_auros_order_id: Dict[int, int] = {}
        self.__drift_order_id_2_auros_order_id: Dict[int, int] = {}

        self.__logger = logging.getLogger("ORDER_CACHE")
        self.__pantheon = pantheon

        self.__finalised_requests_cleanup_after_s = config["finalised_requests_cleanup_after_s"]
        self.__finalised_requests_cleanup_poll_interval_s = config["finalised_requests_cleanup_poll_interval_s"]

    def start(self):
        self.__pantheon.spawn(self.__clear_finalised_orders())

    def get_order_from_auros_order_id(self, auros_order_id: int) -> Order | None:
        return self.__auros_order_id_to_orders.get(auros_order_id, None)

    def get_order_from_drift_user_order_id(self, drift_user_order_id: int) -> Order | None:
        auros_order_id = self.__drift_user_order_id_2_auros_order_id.get(drift_user_order_id, None)

        if auros_order_id:
            return self.__auros_order_id_to_orders.get(auros_order_id, None)

        return None

    def get_order_from_drift_order_id(self, drift_order_id: int) -> Order | None:
        auros_order_id = self.__drift_order_id_2_auros_order_id.get(drift_order_id, None)

        if auros_order_id:
            return self.__auros_order_id_to_orders.get(auros_order_id, None)

        return None

    def is_auros_order_id_in_use(self, auros_order_id: int) -> bool:
        return auros_order_id in self.__auros_order_id_to_orders

    def is_drift_user_order_id_in_use(self, drift_user_order_id: int) -> bool:
        return drift_user_order_id in self.__drift_user_order_id_2_auros_order_id

    def total_drift_user_order_id_in_use(self) -> int:
        return len(self.__drift_user_order_id_2_auros_order_id)

    # the orders returned by this method might update asynchronously
    def get_all_open_orders(self) -> list[Order]:
        open_orders = []
        for order in self.__auros_order_id_to_orders.values():
            if not order.is_finalised():
                open_orders.append(order)

        return open_orders

    def add_or_update(self, order: Order):
        assert order.auros_order_id, "auros order id is not initialised"
        assert order.drift_user_order_id, "drift user order id is not initialised"

        self.__auros_order_id_to_orders[order.auros_order_id] = order
        self.__drift_user_order_id_2_auros_order_id[order.drift_user_order_id] = order.auros_order_id

        if order.drift_order_id:
            self.__drift_order_id_2_auros_order_id[order.drift_order_id] = order.auros_order_id

    def on_finalised(self, auros_order_id: int):
        order = self.get_order_from_auros_order_id(auros_order_id)
        assert order, "ORDER_NOT_FOUND"
        assert order.is_finalised(), "order not finalised"

        self.__drift_user_order_id_2_auros_order_id.pop(order.drift_user_order_id, None)

        # do not clear __drift_order_id_2_auros_order_id mapping as some fills updates might be pending
        # self.__drift_order_id_2_auros_order_id.pop(order.drift_order_id, None)

        order.finalised_at = TimestampNs.now()

    async def __clear_finalised_orders(self):
        while True:
            try:
                await self.__pantheon.sleep(self.__finalised_requests_cleanup_poll_interval_s)
                for auros_order_id in list(self.__auros_order_id_to_orders.keys()):
                    try:
                        order = self.get_order_from_auros_order_id(auros_order_id)
                        if self.__can_clear(order):
                            self.__drift_order_id_2_auros_order_id.pop(order.drift_order_id, None)
                            self.__auros_order_id_to_orders.pop(auros_order_id)
                    except Exception as e:
                        self.__logger.exception(
                            f"Error while checking for finalised orders clean up for auros_order_id={auros_order_id} %r", ex
                        )
            except Exception as ex:
                self.__logger.exception("Error while clearing finalised orders %r", ex)

    def __can_clear(self, order: Order) -> bool:
        return order.finalised_at and (TimestampNs.now() - order.finalised_at) > self.__finalised_requests_cleanup_after_s * 1000_000_000
