from decimal import Decimal
from typing import Any, Dict, List, Union, Literal
from pydantic import BaseModel, Field, RootModel

# Positions and contract data is in the same file just to keep it a bit more compact


class ContractDataItem(BaseModel):
    next_funding_rate: Decimal = Field(..., example="0.0005")
    next_funding_rate_timestamp: int = Field(..., example=1620000000)
    funding_rate: Decimal = Field(..., example="0.0004")
    open_interest: Decimal = Field(..., example="12345.6")
    index_price: Decimal = Field(..., example="60000")
    mark_price: Union[Decimal, Literal["N/A"]] = Field(..., example="60010")


class ContractDataResponse(RootModel[Dict[str, ContractDataItem]]):
    model_config = {
        "json_schema_extra": {
            "example": {
                "BTC-PERP": {
                    "next_funding_rate": "0.0005",
                    "next_funding_rate_timestamp": 1620000000,
                    "funding_rate": "0.0004",
                    "open_interest": "12345.6",
                    "index_price": "60000",
                    "mark_price": "60010"
                },
                "ETH-PERP": {
                    "next_funding_rate": "0.0008",
                    "next_funding_rate_timestamp": 1620000050,
                    "funding_rate": "0.0007",
                    "open_interest": "23456.7",
                    "index_price": "4000",
                    "mark_price": "4005"
                }
            }
        }
    }



class MarketItem(BaseModel):
    base: str = Field(..., example="BTC")
    base_currency: str = Field(..., example="BTC")
    quote_currency: str = Field(..., example="USDC")
    tick_size: Decimal = Field(..., example="0.001")
    min_order_size: Decimal = Field(..., example="0.0001")
    step_order_size: Decimal = Field(..., example="0.0001")
    is_active_on_exchange: bool = Field(..., example=True)
    raw_response: Any = Field(..., example={})
    custom_fields: Dict[str, Any] = Field(
        ...,
        example={"baseDecimals": 8, "quoteDecimals": 6, "nativeIndex": 0}
    )


class MarketsResponse(BaseModel):
    data: List[MarketItem] = Field(...)

    model_config = {
        "json_schema_extra": {
            "example": {
                "data": [
                    {
                        "base": "BTC",
                        "base_currency": "BTC",
                        "quote_currency": "USDC",
                        "tick_size": "0.001",
                        "min_order_size": "0.0001",
                        "step_order_size": "0.0001",
                        "is_active_on_exchange": True,
                        "raw_response": {},
                        "custom_fields": {"baseDecimals": 8, "quoteDecimals": 6, "nativeIndex": 0}
                    }
                ]
            }
        }
    }

