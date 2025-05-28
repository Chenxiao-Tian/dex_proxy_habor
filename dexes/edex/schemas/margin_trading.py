from decimal import Decimal

from typing import Optional, List
from pydantic import BaseModel, Field

class UpdateMarginTradingResponse(BaseModel):
    """
    Response for both enable- and disable-margin-trading endpoints
    """
    account: str = Field(
        ...,
        description="Main account identifier",
        example="alice"
    )
    subaccount: str = Field(
        ...,
        description="Subaccount identifier",
        example="main"
    )
    enabled: bool = Field(
        ...,
        description="Whether margin trading is now enabled",
        example=True
    )
    tx_sig: Optional[str] = Field(
        None,
        description="Transaction signature from the on-chain call",
        example="0xabc123"
    )
    failure: Optional[str] = Field(
        None,
        description="Error message on failure",
        example="Insufficient margin"
    )

    model_config = {
        "json_schema_extra": {
            "examples": {
                "enable_success": {
                    "account": "alice",
                    "subaccount": "main",
                    "enabled": True,
                    "tx_sig": "0xabc123"
                },
                "disable_success": {
                    "account": "alice",
                    "subaccount": "main",
                    "enabled": False,
                    "tx_sig": "0xdef456"
                },
                "error": {
                    "account": "alice",
                    "subaccount": "main",
                    "failure": "Insufficient margin"
                }
            }
        }
    }

class MarginPosition(BaseModel):
    market_index: int = Field(..., example=0)
    name: str = Field(..., example="BTC/USDC")
    size: Decimal = Field(..., example="2")
    entry_price: Decimal = Field(..., example="30000")
    pnl: Decimal = Field(..., example="150")
    market: int = Field(..., example=0)
    size_usd: Decimal = Field(..., example="60000")
    unrealized_pnl: Decimal = Field(..., example="120")


class MarginDataResponse(BaseModel):
    total_collateral: Decimal = Field(..., example="1000")
    maintenance_ratio: Decimal = Field(..., example="2.5")
    available_margin: Decimal = Field(..., example="800")
    maintenance_margin: Decimal = Field(..., example="200")
    total_equity: Decimal = Field(..., example="1000")
    upnl: Decimal = Field(..., example="50")
    perp_positions: List[MarginPosition] = Field(...)

    model_config = {
        "json_schema_extra": {
            "example": {
                "total_collateral": "1000",
                "maintenance_ratio": "2.5",
                "available_margin": "800",
                "maintenance_margin": "200",
                "total_equity": "1000",
                "upnl": "50",
                "perp_positions": [
                    {
                        "market_index": 0,
                        "name": "BTC/USDC",
                        "size": "2",
                        "entry_price": "30000",
                        "pnl": "150",
                        "market": 0,
                        "size_usd": "60000",
                        "unrealized_pnl": "120"
                    }
                ]
            }
        }
    }

