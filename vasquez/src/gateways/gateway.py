import logging
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Callable, Dict, Optional, Any

from common.types import Ccy
from .models import OrderInsertResponse, Side, OrderType


class Gateway(ABC):
    """
    Abstract base class for exchange gateways.
    Provides common functionality and interface for all exchange implementations.
    """

    def __init__(self, config: dict):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)

        # Order tracking
        self.orders: Dict[str, Any] = {}
        self._order_callbacks: Dict[str, Callable] = {}
        self._global_callback: Optional[Callable] = None

    @abstractmethod
    async def start(self, callback: Optional[Callable] = None):
        """
        Initialize the gateway connection

        Args:
            callback: Optional global callback for all order updates
        """
        self._global_callback = callback

    @abstractmethod
    async def stop(self):
        """Close all connections and clean up resources"""
        pass

    @abstractmethod
    async def place_order(
        self,
        instrument: str,
        side: Side,
        order_type: OrderType,
        price: Decimal,
        quantity: Decimal,
        client_order_id: Optional[str] = None,
        callback: Optional[Callable] = None,
    ) -> OrderInsertResponse:
        """
        Place an order on the exchange

        Args:
            symbol: Trading pair symbol
            side: BUY or SELL
            order_type: Type of order (e.g., LIMIT, MARKET)
            price: Order price
            quantity: Order quantity
            client_order_id: Optional client order ID
            callback: Optional callback for order updates

        Returns:
            OrderInsertResponse: Response containing order details
        """
        pass

    @abstractmethod
    async def cancel_order(
        self, instrument: str, order_id: int, exchange_order_id: str
    ) -> bool:
        """
        Cancel an existing order either by order ID or exchange order ID

        Args:
            iid: Instrument ID of the order
            client_order_id: The client order ID to cancel
            exchange_order_id: The exchange order ID to cancel

        Returns:
            bool: True if cancellation was successful
        """
        pass

    @abstractmethod
    async def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        """
        Cancel all open orders, optionally filtered by symbol

        Args:
            symbol: Optional trading pair to limit cancellation to

        Returns:
            int: Number of orders cancelled
        """
        pass

    @abstractmethod
    async def get_order_status(
        self, instrument: str, order_id: int, exchange_order_id: int
    ) -> Optional[dict]:
        """
        Get the current status of an order

        Args:
            iid: Instrument ID of the order
            client_order_id: The client order ID to query
            exchange_order_id: The exchange order ID to query

        Returns:
            dict: Order status information or None if not found
        """
        pass

    @abstractmethod
    async def get_available_balance(self, ccy: Ccy) -> Decimal:
        pass

    def _generate_client_order_id(self, prefix: str = "") -> str:
        """
        Generate a unique client order ID

        Args:
            prefix: Optional prefix for the ID

        Returns:
            str: Unique client order ID
        """
        import time
        import uuid

        timestamp = int(time.time() * 1000)
        random_suffix = str(uuid.uuid4())[:8]

        if prefix:
            return f"{prefix}-{timestamp}-{random_suffix}"
        return f"{timestamp}-{random_suffix}"

    def register_order_callback(self, client_order_id: str, callback: Callable):
        """
        Register a callback for a specific order

        Args:
            client_order_id: The client order ID to watch
            callback: Callback function to call on updates
        """
        self._order_callbacks[client_order_id] = callback

    def unregister_order_callback(self, client_order_id: str):
        """
        Unregister a callback for a specific order

        Args:
            client_order_id: The client order ID to stop watching
        """
        if client_order_id in self._order_callbacks:
            del self._order_callbacks[client_order_id]
