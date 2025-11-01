from decimal import Decimal
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field, ConfigDict


class CreateOrderRequest(BaseModel):
    client_order_id: str = Field(
        ...,
        description="Client-provided unique order identifier",
        examples=["123"]
    )
    symbol: str = Field(
        ...,
        description="Trading pair symbol",
        examples=["BTC/USDC"]
    )
    price: str = Field(
        ...,
        description="Order price",
        examples=["50000.0"]
    )
    quantity: str = Field(
        ...,
        description="Order quantity",
        examples=["0.1"]
    )
    side: Literal["BUY", "SELL"] = Field(
        ...,
        description="Order side",
        examples=["BUY"]
    )
    order_type: str = Field(
        ...,
        description="Type of the order, e.g. LIMIT or MARKET",
        examples=["LIMIT"]
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "client_order_id": "123",
                "symbol": "BTC/USDC",
                "price": "50000.0",
                "quantity": "0.1",
                "side": "BUY",
                "order_type": "LIMIT"
            }
        }
    )


class TradeDetail(BaseModel):
    exchange_order_id: str = Field(..., examples=["abc123"])
    exchange_trade_id: str = Field(..., examples=["def456"])
    symbol: str = Field(..., examples=["BTC/USDC"])
    side: Literal["BUY", "SELL"] = Field(..., examples=["BUY"])
    amount: Decimal = Field(..., examples=["0.1"])
    price: Decimal = Field(..., examples=["50000.0"])
    exchange_timestamp: int = Field(..., examples=[1620000000])
    fee: Decimal = Field(..., examples=["0.0001"])
    fee_ccy: str = Field(..., examples=["USDC"])
    liquidity: str = Field(..., examples=["TAKER"])
    raw_response: Dict[str, Any] = Field(..., examples=[{}])

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


class OrderResponse(BaseModel):
    client_order_id: str = Field(..., examples=["123"])
    order_id: str = Field(..., examples=["456"])
    price: str = Field(..., examples=["50000.0"])
    quantity: str = Field(..., examples=["0.1"])
    total_exec_quantity: str = Field(..., examples=["0.05"])
    last_update_timestamp_ns: int = Field(..., examples=[1620000000000000000])
    status: str = Field(..., examples=["FILLED"])
    reason: Optional[str] = Field(None, examples=[None])
    trades: List[TradeDetail] = Field(
        ...,
        description="List of trades (fills) executed for this order",
        examples=[]
    )
    order_type: str = Field(..., examples=["LIMIT"])
    symbol: str = Field(..., examples=["BTC/USDC"])
    side: Literal["BUY", "SELL"] = Field(..., examples=["BUY"])
    place_tx_id: str = Field(..., examples=["0xSIG"])
    send_timestamp_ns: int = Field(..., examples=[1620000001000000000])

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


class OrderErrorResponse(BaseModel):
    error_code: str = Field(..., examples=["TRANSPORT_FAILURE"])
    error_message: str = Field(..., examples=["Order could not be placed"])

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
        examples=["123"]
    )

class QueryLiveOrdersResponse(BaseModel):
    send_timestamp_ns: int = Field(..., example=[1620000001000000000])
    orders: List[OrderResponse] = Field(..., examples=[[]])

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
                        "send_timestamp_ns": 1620000001000000000
                    }
                ]
            }
        }
    }

