from decimal import Decimal
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field


class GetTransfersRequest(BaseModel):
    start_timestamp: int = Field(..., example=1620000000)
    end_timestamp: int = Field(..., example=1620000000)
    include_raw: bool = Field(..., example=True)
    next_page: Optional[str] = Field(
        None,
        description="Page token for pagination",
        example="1",
    )


class TransferRecord(BaseModel):
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
    next_page: str = Field(..., example="1")
    records: List[TransferRecord] = Field(...)

    model_config = {
        "json_schema_extra": {
            "example": {
                "next_page": "1",
                "records": [
                    {
                        "symbol": "BTC",
                        "tx_hash": "0x123",
                        "amount": "0.5",
                        "type": "withdrawal",
                        "created_timestamp": "1620000000.0",
                        "raw_response": {}
                    }
                ]
            }
        }
    }

