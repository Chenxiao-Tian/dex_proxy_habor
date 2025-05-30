from decimal import Decimal
from typing import Any, Dict, List, Union, Literal
from pydantic import BaseModel, Field


class InstrumentData(BaseModel):
    native_code: str = Field(..., example="BTC/USDC")
    open_interest: Decimal = Field(..., example="12345.6")
    index_price: Decimal = Field(..., example="60000")
    mark_price: Union[Decimal, Literal["N/A"]] = Field(..., example="60010") 
    next_funding_rate: Decimal = Field(..., example="0.0005")
    next_funding_rate_timestamp: int = Field(..., example=1620000000)
    raw_response: Dict[str, Any] = Field(..., example={})


class InstrumentDataResponse(BaseModel):
    instruments: List[InstrumentData] = Field(...)

    model_config = {
        "json_schema_extra": {
            "example": {
                "instruments": [
                    {
                        "native_code": "BTC/USDC",
                        "open_interest": "12345.6",
                        "index_price": "60000",
                        "mark_price": "60010",
                        "next_funding_rate": "0.0005",
                        "next_funding_rate_timestamp": 1620000000,
                        "raw_response": {}
                    }
                ]
            }
        }
    }