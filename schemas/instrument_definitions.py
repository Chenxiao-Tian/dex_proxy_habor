from decimal import Decimal
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class InstrumentDefinitionData(BaseModel):
    native_code: str = Field(..., example="BTC/USD")
    base_currency: str = Field(..., example="BTC")
    quote_currency: str = Field(..., example="USDC")
    settlement_currency: str = Field(..., example="USDC")
    kind: str= Field(..., example="swap")
    tick_size: Decimal = Field(..., example="0.001")
    min_order_size: Decimal = Field(..., example="1")
    min_order_incremental_size: Decimal = Field(..., example="0.0001")
    is_active_on_exchange: bool = Field(..., example=True)
    making_fee_in_bps: Decimal = Field(..., example="0.2")
    taking_fee_in_bps: Decimal = Field(..., example="2.5")
    swap_funding_period: Optional[Decimal] = Field(..., example="480")
    swap_funding_base_rate_bps: Optional[Decimal] = Field(..., example="1")
    
    raw_response: Any = Field(..., example={})
    custom_fields: Dict[str, Any] = Field(
        ...,
        example={"baseDecimals": 8, "quoteDecimals": 6, "nativeIndex": 0}
    )


class InstrumentDefinitionDataResponse(BaseModel):
    instruments: List[InstrumentDefinitionData] = Field(...)

    model_config = {
        "json_schema_extra": {
            "example": {
                "instruments": [
                    {
                        "native_code": "BTC/USDC",
                        "base_currency": "2",
                        "quote_currency": "30000",
                        "settlement_currency": "150",
                        "kind": "swap",
                        "tick_size": "60000",
                        "min_order_size": "0.0001",
                        "min_order_incremental_size": "1",
                        "is_active_on_exchange": True,
                        "making_fee_in_bps": "0.2",
                        "taking_fee_in_bps": "2.5",
                        "swap_funding_period": "480",
                        "swap_funding_base_rate_bps": "1",
                        "raw_response": {},
                        "custom_fields": {}
                    }
                ]
            }
        }
    }