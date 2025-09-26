from decimal import Decimal
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field, ConfigDict


class CreateOrderRequest(BaseModel):
    client_order_id: str = Field(
        ..., description="Client-provided unique order identifier", example="123"
    )
    symbol: str = Field(..., description="Trading pair symbol", example="BTC/USDC")
    price: Decimal = Field(..., description="Order price", example="50000.0")
    quantity: Decimal = Field(..., description="Order quantity", example="0.1")
    side: Literal["BUY", "SELL"] = Field(..., description="Order side", example="BUY")
    order_type: Literal["GTC", "GTC_POST_ONLY", "IOC"] = Field(
        ...,
        description="Type of the order",
        example="GTC_POST_ONLY",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "client_order_id": "123",
                "symbol": "BTC/USDC",
                "price": "50000.0",
                "quantity": "0.1",
                "side": "BUY",
                "order_type": "IOC",
            }
        }
    )


class TradeDetail(BaseModel):
    exchange_order_id: str = Field(..., example="abc123")
    trade_id: str = Field(..., example="def456")
    symbol: str = Field(..., example="BTC/USDC")
    side: Literal["BUY", "SELL"] = Field(..., example="BUY")
    exec_quantity: Decimal = Field(..., example="0.1")
    exec_price: Decimal = Field(..., example="50000.0")
    exch_timestamp_ns: int = Field(..., example=1620000000)
    fee: Decimal = Field(..., example="0.0001")
    fee_ccy: str = Field(..., example="USDC")
    liquidity: Literal["Taker", "Maker"] = Field(..., example="Taker")
    raw_response: Dict[str, Any] = Field(..., example={})

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "exchange_order_id": "abc123",
                "trade_id": "def456",
                "symbol": "BTC/USDC",
                "side": "BUY",
                "exec_quantity": "0.1",
                "exec_price": "50000.0",
                "exch_timestamp_ns": 1620000000,
                "fee": "0.0001",
                "fee_ccy": "USDC",
                "liquidity": "Taker",
                "raw_response": {},
            }
        }
    )


class OrderResponse(BaseModel):
    client_order_id: int = Field(..., example=123)
    order_id: str = Field(..., example="456")
    price: Decimal = Field(..., example="50000.0")
    quantity: Decimal = Field(..., example="0.1")
    total_exec_quantity: Decimal = Field(..., example="0.05")
    last_update_timestamp_ns: int = Field(..., example=1620000000000000000)
    status: str = Field(..., example="FILLED")
    reason: Optional[str] = Field(None, example=None)
    trades: List[TradeDetail] = Field(
        ..., description="List of trades (fills) executed for this order", example=[]
    )
    order_type: str = Field(..., example="IOC")
    symbol: str = Field(..., example="BTC/USDC")
    side: Literal["BUY", "SELL"] = Field(..., example="BUY")
    place_tx_sig: str = Field(..., example="0xSIG")
    send_timestamp_ns: int = Field(..., example=1620000001000000000)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "client_order_id": 123,
                "order_id": "456",
                "price": "50000.0",
                "quantity": "0.1",
                "total_exec_quantity": "0.05",
                "last_update_timestamp_ns": 1620000000000000000,
                "status": "FILLED",
                "reason": None,
                "trades": [],
                "order_type": "IOC",
                "symbol": "BTC/USDC",
                "side": "BUY",
                "place_tx_sig": "0xSIG",
                "send_timestamp_ns": 1620000001000000000,
            }
        }
    )


class _OrderResponse(BaseModel):
    client_order_id: int = Field(..., example=123)
    order_id: str = Field(..., example="456")
    price: Decimal = Field(..., example="50000.0")
    quantity: Decimal = Field(..., example="0.1")
    total_exec_quantity: Decimal = Field(..., example="0.05")
    last_update_timestamp_ns: int = Field(..., example=1620000000000000000)
    status: str = Field(..., example="FILLED")
    reason: Optional[str] = Field(None, example=None)
    trades: List[TradeDetail] = Field(
        ..., description="List of trades (fills) executed for this order", example=[]
    )
    order_type: str = Field(..., example="IOC")
    symbol: str = Field(..., example="BTC/USDC")
    side: Literal["BUY", "SELL"] = Field(..., example="BUY")
    place_tx_sig: str = Field(..., example="0xSIG")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "client_order_id": 123,
                "order_id": "456",
                "price": "50000.0",
                "quantity": "0.1",
                "total_exec_quantity": "0.05",
                "last_update_timestamp_ns": 1620000000000000000,
                "status": "FILLED",
                "reason": None,
                "trades": [],
                "order_type": "IOC",
                "symbol": "BTC/USDC",
                "side": "BUY",
                "place_tx_sig": "0xSIG",
            }
        }
    )


class QueryLiveOrdersResponse(BaseModel):
    send_timestamp_ns: int = Field(..., example=1620000001000000000)
    orders: List[_OrderResponse] = Field(..., example=[])

    model_config = {
        "json_schema_extra": {
            "example": {
                "send_timestamp_ns": 1620000001000000000,
                "orders": [
                    {
                        "client_order_id": 123,
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


class CreateOrderErrorResponse(BaseModel):
    error_code: str = Field(..., example="TRANSPORT_FAILURE")
    error_message: str = Field(..., example="Order could not be placed")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "error_code": "TRANSPORT_FAILURE",
                "error_message": "Order could not be placed",
            }
        }
    )


class QueryOrderParams(BaseModel):
    client_order_id: str = Field(
        ..., description="ID of the client order to query", example="123"
    )
