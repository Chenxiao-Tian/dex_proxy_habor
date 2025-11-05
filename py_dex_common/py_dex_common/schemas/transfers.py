from decimal import Decimal
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field


class GetTransfersRequest(BaseModel):
    start_timestamp: int = Field(..., example=1620000000)
    end_timestamp: int = Field(..., example=1620000000)
    include_raw: bool = Field(..., example=True)

class TransferRecord(BaseModel):
    account: str = Field(..., example="spot")
    symbol: str = Field(..., example="BTC")
    tx_hash: str = Field(..., example="0x123")
    amount: Decimal = Field(..., example="0.5")
    type: Literal[
        "withdrawal",
        "deposit",
        "internal_deposit",
        "internal_withdrawal"
    ] = Field(..., example="withdrawal")
    created_timestamp: int = Field(..., example=1620000000)
    raw_response: Dict[str, Any] = Field(..., example={})


class TransfersResponse(BaseModel):
    records: List[TransferRecord] = Field(...)

    model_config = {
        "json_schema_extra": {
            "example": {
                "records": [
                    {
                        "account": "spot",
                        "symbol": "BTC",
                        "tx_hash": "0x123",
                        "amount": "0.5",
                        "type": "internal_withdrawal",
                        "created_timestamp": "1620000000.0",
                        "raw_response": {}
                    }
                ]
            }
        }
    }

