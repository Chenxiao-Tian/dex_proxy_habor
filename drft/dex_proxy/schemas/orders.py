from decimal import Decimal
from typing import List, Optional, Literal
from pydantic import BaseModel, Field

from py_dex_common.schemas import TradeDetail


class OrderResponse(BaseModel):
    client_order_id: str = Field(..., example="123")
    order_id: str = Field(..., example="456")
    price: Decimal = Field(..., example="50000.0")
    quantity: Decimal = Field(..., example="0.1")
    total_exec_quantity: Decimal = Field(..., example="0.05")
    last_update_timestamp_ns: int = Field(..., example=1620000000000000000)
    status: str = Field(..., example="FILLED")
    reason: Optional[str] = Field(None, example=None)
    trades: List[TradeDetail] = Field(..., example=[])
    order_type: str = Field(..., example="LIMIT")
    symbol: str = Field(..., example="BTC/USDC")
    side: Literal["BUY", "SELL"] = Field(..., example="BUY")
    place_tx_sig: str = Field(..., example="0xSIG")

    model_config = {
        "json_schema_extra": {
            "example": {
                "client_order_id": "123",
                "order_id": "456",
                "price": "50000.0",
                "quantity": "0.1",
                "total_exec_quantity": "0.05",
                "last_update_timestamp_ns": 1620000000000000000,
                "status": "FILLED",
                "reason": None,
                "trades": [],
                "order_type": "LIMIT",
                "symbol": "BTC/USDC",
                "side": "BUY",
                "place_tx_sig": "0xSIG",
            }
        }
    }


class QueryLiveOrdersResponse(BaseModel):
    send_timestamp_ns: int = Field(..., example=1620000001000000000)
    orders: List[OrderResponse] = Field(..., example=[])

    model_config = {
        "json_schema_extra": {
            "example": {
                "send_timestamp_ns": 1620000001000000000,
                "orders": [
                    {
                        "client_order_id": "123",
                        "order_id": "456",
                        "price": "50000.0",
                        "quantity": "0.1",
                        "total_exec_quantity": "0.05",
                        "last_update_timestamp_ns": 1620000000000000000,
                        "status": "FILLED",
                        "reason": None,
                        "trades": [],
                        "order_type": "LIMIT",
                        "symbol": "BTC/USDC",
                        "side": "BUY",
                        "place_tx_sig": "0xSIG",
                    }
                ],
            }
        }
    }
