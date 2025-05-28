from decimal import Decimal
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field


class FetchTransferRecordsParams(BaseModel):
    next_page: Optional[str] = Field(
        None,
        description="Page token for pagination",
        example="1",
    )


class FetchFundingRecordsParams(BaseModel):
    next_page: Optional[str] = Field(
        None,
        description="Page token for pagination",
        example="1",
    )


class FetchTradesParams(BaseModel):
    next_page: Optional[str] = Field(
        None,
        description="Page token for pagination",
        example="1",
    )



class TransferRecord(BaseModel):
    symbol: str = Field(..., example="BTC")
    exchange_id: str = Field(..., example="0x123")
    amount: Decimal = Field(..., example="0.5")
    type: Literal[
        "withdrawal",
        "deposit",
        "internal_deposit",
        "internal_withdrawal"
    ] = Field(..., example="withdrawal")
    created_timestamp: Decimal = Field(..., example="1620000000.0")
    raw_response: Dict[str, Any] = Field(..., example={})


class FundingRecord(BaseModel):
    symbol: str = Field(..., example="BTC/USDC")
    exchange_id: str = Field(..., example="0x123")
    amount: Decimal = Field(..., example="0.01")
    created_timestamp: Decimal = Field(..., example="1620000000.0")
    raw_response: Dict[str, Any] = Field(..., example={})


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


# --- Response models ---

class TransfersResponse(BaseModel):
    next_page: str = Field(..., example="1")
    records: List[TransferRecord] = Field(...)

    model_config = {
        "json_schema_extra": {
            "example": {
                "next_page": "1",
                "records": [
                    {
                        "symbol": "BTC",
                        "exchange_id": "0x123",
                        "amount": "0.5",
                        "type": "withdrawal",
                        "created_timestamp": "1620000000.0",
                        "raw_response": {}
                    }
                ]
            }
        }
    }


class FundingResponse(BaseModel):
    next_page: str = Field(..., example="1")
    records: List[FundingRecord] = Field(...)

    model_config = {
        "json_schema_extra": {
            "example": {
                "next_page": "1",
                "records": [
                    {
                        "symbol": "BTC/USDC",
                        "exchange_id": "0x123",
                        "amount": "0.01",
                        "created_timestamp": "1620000000.0",
                        "raw_response": {}
                    }
                ]
            }
        }
    }


class TradesResponse(BaseModel):
    next_page: str = Field(..., example="1")
    records: List[TradeRecord] = Field(...)

    model_config = {
        "json_schema_extra": {
            "example": {
                "next_page": "1",
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

