from decimal import Decimal
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field, ConfigDict


class CreateOrderRequest(BaseModel):
    client_order_id: int = Field(
        ...,
        description="Client-provided unique order identifier",
        example=123
    )
    symbol: str = Field(
        ...,
        description="Trading pair symbol",
        example="BTC/USDC"
    )
    price: Decimal = Field(
        ...,
        description="Order price",
        example="50000.0"
    )
    quantity: Decimal = Field(
        ...,
        description="Order quantity",
        example="0.1"
    )
    side: Literal["BUY", "SELL"] = Field(
        ...,
        description="Order side",
        example="BUY"
    )
    order_type: str = Field(
        ...,
        description="Type of the order, e.g. LIMIT or MARKET",
        example="LIMIT"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "client_order_id": 123,
                "symbol": "BTC/USDC",
                "price": "50000.0",
                "quantity": "0.1",
                "side": "BUY",
                "order_type": "LIMIT"
            }
        }
    )


class TradeDetail(BaseModel):
    exchange_order_id: str = Field(..., example="abc123")
    exchange_trade_id: str = Field(..., example="def456")
    symbol: str = Field(..., example="BTC/USDC")
    side: Literal["BUY", "SELL"] = Field(..., example="BUY")
    amount: Decimal = Field(..., example="0.1")
    price: Decimal = Field(..., example="50000.0")
    exchange_timestamp: int = Field(..., example=1620000000)
    fee: Decimal = Field(..., example="0.0001")
    fee_ccy: str = Field(..., example="USDC")
    liquidity: str = Field(..., example="TAKER")
    raw_response: Dict[str, Any] = Field(..., example={})

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "exchange_order_id": "abc123",
                "exchange_trade_id": "def456",
                "symbol": "BTC/USDC",
                "side": "BUY",
                "amount": "0.1",
                "price": "50000.0",
                "exchange_timestamp": 1620000000,
                "fee": "0.0001",
                "fee_ccy": "USDC",
                "liquidity": "TAKER",
                "raw_response": {}
            }
        }
    )


class CreateOrderResponse(BaseModel):
    client_order_id: str = Field(..., example="123")
    order_id: str = Field(..., example="456")
    price: Decimal = Field(..., example="50000.0")
    quantity: Decimal = Field(..., example="0.1")
    total_exec_quantity: Decimal = Field(..., example="0.05")
    last_update_timestamp_ns: int = Field(..., example=1620000000000000000)
    status: str = Field(..., example="FILLED")
    reason: Optional[str] = Field(None, example=None)
    trades: List[TradeDetail] = Field(
        ...,
        description="List of trades (fills) executed for this order",
        example=[]
    )
    order_type: str = Field(..., example="LIMIT")
    symbol: str = Field(..., example="BTC/USDC")
    side: Literal["BUY", "SELL"] = Field(..., example="BUY")
    place_tx_sig: str = Field(..., example="0xSIG")
    send_timestamp_ns: int = Field(..., example=1620000001000000000)

    model_config = ConfigDict(
        json_schema_extra={
            "examples": {
                "create_success": {
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
                    "send_timestamp_ns": 1620000001000000000
                }
            }
        }
    )


class CreateOrderErrorResponse(BaseModel):
    error_code: str = Field(..., example="TRANSPORT_FAILURE")
    error_message: str = Field(..., example="Order could not be placed")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "error_code": "TRANSPORT_FAILURE",
                "error_message": "Order could not be placed"
            }
        }
    )




class QueryOrderParams(BaseModel):
    client_order_id: str = Field(
        ...,
        description="ID of the client order to query",
        example="123"
    )


class QueryOrderResponse(BaseModel):
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
    send_timestamp_ns: int = Field(..., example=1620000001000000000)

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
                "send_timestamp_ns": 1620000001000000000
            }
        }
    }
