from decimal import Decimal

from typing import List
from pydantic import BaseModel, Field


class MarginPosition(BaseModel):
    symbol: str = Field(..., example="BTC/USDC")
    position: Decimal = Field(..., example="2")
    upnl: Decimal = Field(..., example="150")
    rpnl: Decimal = Field(..., example="150")
    
class UnifiedMargin(BaseModel):
    total_collateral: Decimal = Field(..., example="1000")
    maintenance_ratio: Decimal = Field(..., example="2.5")
    available_margin: Decimal = Field(..., example="800")
    maintenance_margin: Decimal = Field(..., example="200")
    total_equity: Decimal = Field(..., example="1000")
    upnl: Decimal = Field(..., example="50")
    rpnl: Decimal = Field(..., example="150")

# Cross margin?

class MarginDataResponse(BaseModel):
    unified_margin: UnifiedMargin = Field(...)
    positions: List[MarginPosition] = Field(...)

    model_config = {
        "json_schema_extra": {
            "example": {
                "unified_margin": {
                    "total_collateral": "1000",
                    "maintenance_ratio": "2.5",
                    "available_margin": "800",
                    "maintenance_margin": "200",
                    "total_equity": "1000",
                    "upnl": "50",
                    "rpnl": "150"
                },
                "positions": [
                    {
                        "symbol": "BTC/USDC",
                        "position": "2",
                        "upnl": "120",
                        "rpnl": "150"
                    }
                ]
            }
        }
    }

