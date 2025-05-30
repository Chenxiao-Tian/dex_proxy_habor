from decimal import Decimal
from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field

from .order_trade import TradeDetail


class CancelOrderParams(BaseModel):
    client_order_id: str = Field(
        ...,
        description="ID of the client order to cancel",
        example="123"
    )


class CancelOrderSuccess(BaseModel):
    client_request_id: str = Field(..., example="123")
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
    send_timestamp_ns: int = Field(..., example=1620000001000000000)
    tx_sig: Optional[str] = Field(None, example="0xDEADBEEF")

    model_config = {
        "json_schema_extra": {
            "example": {
                "client_request_id": "123",
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
                "send_timestamp_ns": 1620000001000000000,
                "tx_sig": "0xDEADBEEF"
            }
        }
    }


class CancelOrderErrorResponse(BaseModel):
    error_code: str = Field(
        ...,
        description="Error code indicating why cancellation failed",
        example="ORDER_NOT_FOUND"
    )
    error_message: str = Field(
        ...,
        description="Human-readable error message",
        example="order 123 not found"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "error_code": "ORDER_NOT_FOUND",
                "error_message": "order 123 not found"
            }
        }
    }


class CancelAllOrdersResponse(BaseModel):
    cancelled: List[int] = Field(
        ...,
        description="List of auros_order_id values that were cancelled",
        example=[1, 2, 3]
    )
    send_timestamp_ns: int = Field(
        ...,
        description="Timestamp when the cancel-all tx was submitted",
        example=1620000001000000000
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "cancelled": [1, 2, 3],
                "send_timestamp_ns": 1620000001000000000
            }
        }
    }

