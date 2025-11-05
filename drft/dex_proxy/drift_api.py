import logging
from decimal import Decimal
from enum import auto
from typing import List, Optional, Literal, Any

from pantheon.pantheon_types import OrderType, Side
from pantheon.timestamp_ns import TimestampNs
from pantheon.utils import SerialisableEnum

from driftpy.constants.numeric_constants import BASE_PRECISION, PRICE_PRECISION
from driftpy.decode.utils import decode_name
from driftpy.drift_client import DriftClient
from driftpy.math.conversion import convert_to_number


logger = logging.getLogger("drift_api")
MarketType = Literal["spot", "perp"]


# https://github.com/drift-labs/driftpy/issues/220
def equal_drift_enum(a: Any, b: Any):
    return a.index == b.index


def equal_drift_enum_str(a: Any, b: Any):
    a_str = str(a).lower()
    b_str = str(b).lower()
    return a_str in b_str or b_str in a_str


class OrderStatus(SerialisableEnum):
    OPEN = auto()
    REJECTED = auto()
    CANCELLED = auto()
    EXPIRED = auto()
    # PENDING = auto()


class OrderTrade:
    def __init__(
        self,
        trade_id: str,
        exec_price: Decimal,
        exec_qty: Decimal,
        liquidity: Literal["Maker", "Taker"],
        exch_timestamp: TimestampNs,
    ):
        self.trade_id = trade_id
        self.exec_price = exec_price
        self.exec_qty = exec_qty
        self.liquidity = liquidity
        self.exch_timestamp = exch_timestamp


class Order:
    def __init__(
        self,
        received_at: TimestampNs,
        auros_order_id: Optional[int],
        drift_user_order_id: Optional[int],
        drift_order_id: Optional[int],
        sub_account_id: int,
        sub_account_public_key: str,
        price: Decimal,
        qty: Decimal,
        side: Side,
        order_type: OrderType,
        symbol: str,
        slot: int,
        status: OrderStatus = OrderStatus.OPEN,
    ):
        self.received_at = received_at
        self.auros_order_id = auros_order_id
        self.drift_user_order_id = drift_user_order_id
        self.drift_order_id = drift_order_id
        self.sub_account_id: int = sub_account_id
        self.sub_account_public_key: str = sub_account_public_key
        self.price: Decimal = price
        self.qty: Decimal = qty
        self.side: Side = side
        self.order_type: OrderType = order_type
        self.symbol: str = symbol

        # the actual slot of the order placement will be greater than or equal to self.slot
        self.slot: int = slot
        self.place_tx_sig: str = ""
        self.place_tx_confirmed: bool = False

        self.drift_market_index: Optional[int] = None
        self.drift_market_type: Optional[MarketType] = None
        self.price_mult: int = 0
        self.qty_mult: int = 0

        self.total_executed_qty: Decimal = Decimal(0)
        self.last_update: TimestampNs = TimestampNs.now()
        self.status: OrderStatus = status
        self.reason: str = ""

        self.seen_trades_id = set()
        self.trades: List[OrderTrade] = []

        self.last_order_action_record_poll_success_at: TimestampNs = None
        self.finalised_at: TimestampNs = None

    def fill_market(
        self, market_index: int, market_type: str | MarketType, client: DriftClient
    ):
        self.drift_market_index = market_index
        if equal_drift_enum_str(market_type, "Perp"):
            self.qty_mult = BASE_PRECISION
            self.price_mult = PRICE_PRECISION
            self.drift_market_type = "perp"
        elif equal_drift_enum_str(market_type, "Spot"):
            spot = client.get_spot_market_account(self.drift_market_index)
            self.qty_mult = pow(10, spot.decimals)
            self.price_mult = PRICE_PRECISION
            self.drift_market_type = "spot"
        else:
            raise Exception(f"Unknown market type {market_type}")

    def is_finalised(self):
        return self.status != OrderStatus.OPEN


__all__ = [
    "decode_name",
    "equal_drift_enum",
    "convert_to_number",
    "OrderStatus",
    "OrderTrade",
    "Order",
]
