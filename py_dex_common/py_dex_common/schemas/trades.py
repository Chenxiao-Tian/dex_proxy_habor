from decimal import Decimal
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field
from pantheon.timestamp_ns import TimestampNs
from datetime import datetime, timedelta


class GetTradesRequest(BaseModel):
    start_timestamp: int = Field(..., example=TimestampNs.from_datetime(datetime.now() - timedelta(hours=1)).get_ns_since_epoch())
    end_timestamp: int = Field(..., example=TimestampNs.now().get_ns_since_epoch())
    client_order_id: Optional[str] = Field(default=None, example="123")
    include_raw: bool = Field(..., example=True)


class TradeRecord(BaseModel):
    exchange_order_id: str = Field(..., example="abc123")
    exchange_trade_id: str = Field(..., example="def456")
    symbol: str = Field(..., example="BTC/USDC")
    side: Literal["BUY", "SELL"] = Field(..., example="BUY")
    amount: Decimal = Field(..., example="0.1")
    price: Decimal = Field(..., example="60000")
    exchange_timestamp: int = Field(..., example=1620000000)
    fee: Decimal = Field(..., example="0.0001")
    fee_ccy: str = Field(..., example="USDC")
    liquidity: str = Field(..., example="TAKER")
    raw_response: Dict[str, Any] = Field(..., example={})


class TradesResponse(BaseModel):
    records: List[TradeRecord] = Field(...)

    model_config = {
        "json_schema_extra": {
            "example": {
                "records": [
                    {
                        "exchange_order_id": "abc123",
                        "exchange_trade_id": "def456",
                        "symbol": "BTC/USDC",
                        "side": "BUY",
                        "amount": "0.1",
                        "price": "60000",
                        "exchange_timestamp": 1620000000,
                        "fee": "0.0001",
                        "fee_ccy": "USDC",
                        "liquidity": "TAKER",
                        "raw_response": {}
                    }
                ]
            }
        }
    }

