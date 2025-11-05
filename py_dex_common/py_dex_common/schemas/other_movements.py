from decimal import Decimal
from typing import Any, Dict, List, Literal
from pydantic import BaseModel, Field


class GetOtherMovementsRequest(BaseModel):
    start_timestamp: int = Field(..., example=1620000000)
    end_timestamp: int = Field(..., example=1620000000)
    include_raw: bool = Field(..., example=True)


class OtherMovementsRecord(BaseModel):
    type: Literal[
        'trade',
        'funding',
        'fee',
        'rebate',
        'interest',
        'other_expense',
        'other_revenue',
        'settlement',
        'airdrop',
        'staking_reward',
        'unclassified',
        'adjustment',
        'vest'
    ] = Field(..., example="funding")
    account: str = Field(..., example="spot")
    symbol: str = Field(..., example="USDC")
    related_symbol: str = Field(..., example="BTC/USDC")
    tx_hash: str = Field(..., example="0x123")
    amount: Decimal = Field(..., example="0.01")
    created_timestamp: int = Field(..., example=1620000000)
    raw_response: Dict[str, Any] = Field(..., example={})


class OtherMovementsResponse(BaseModel):
    records: List[OtherMovementsRecord] = Field(...)

    model_config = {
        "json_schema_extra": {
            "example": {
                "records": [
                    {
                        "type": "funding",
                        "account": "spot",
                        "symbol": "USDC",
                        "related_symbol": "BTC/USDC",
                        "tx_hash": "0x123",
                        "amount": "0.01",
                        "created_timestamp": "1620000000.0",
                        "raw_response": {}
                    }
                ]
            }
        }
    }

