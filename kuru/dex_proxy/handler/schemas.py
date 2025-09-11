from enum import Enum
from typing import TypedDict

class ErrorCode(str, Enum):
    EXCHANGE_REJECTION = "EXCHANGE_REJECTION"
    INVALID_PARAMETER = "INVALID_PARAMETER"
    ORDER_NOT_FOUND = "ORDER_NOT_FOUND"

class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    LIMIT_POST_ONLY = "LIMIT_POST_ONLY"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    OPEN = "OPEN"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    # TODO: This status should be deleted in favour of CANCELLED
    CANCELLED_PENDING = "CANCELLED_PENDING"
    REJECTED = "REJECTED"


class CreateOrderIn(TypedDict):
    price: str
    quantity: str
    client_order_id: str
    side: OrderSide
    order_type: OrderType
    symbol: str

class OrderIn(TypedDict):
    client_order_id: str

class CancelOrderIn(TypedDict):
    client_order_id: str

class CreateOrderOut(TypedDict):
    client_order_id: int
    order_id: str
    price: str
    quantity: str
    total_exec_quantity: str
    last_update_timestamp_ns: int
    status: str
    trades: list[dict]
    order_type: str
    symbol: str
    side: str
    send_timestamp_ns: int
    tx_hash: str
