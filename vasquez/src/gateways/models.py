from dataclasses import dataclass
from decimal import Decimal
from enum import Enum, auto


class Side(Enum):
    BUY = auto()
    SELL = auto()
    BID = BUY
    ASK = SELL

    def __mul__(self, other: Decimal) -> Decimal:
        return other * (Decimal("1") if self is Side.BUY else Decimal("-1"))

    def __rmul__(self, other: Decimal) -> Decimal:
        return self * other

class OrderType(Enum):
    Limit = auto()
    Market = auto()

@dataclass
class OrderInsertResponse:
    order_id: str
    client_order_id: str
    exec_qty: Decimal
    rem_qty: Decimal
    price: Decimal
    side: Side
    status: str
