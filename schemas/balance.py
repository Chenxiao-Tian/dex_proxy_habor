from decimal import Decimal
from typing import Dict, List, Optional
from pydantic import BaseModel, Field, RootModel


class BalanceItem(BaseModel):
    symbol: str = Field(..., example="SOL")
    balance: Decimal = Field(..., example="0.5")


class BalanceResponse(BaseModel):
    balances: Dict[str, List[BalanceItem]] = Field(
        ...,
        description="List of balances by account"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "balances": {
                    "wallet": [
                        {
                            "symbol": "BTC",
                            "balance": "0.01"
                        },
                        {
                            "symbol": "ETH",
                            "balance": "2"
                        }
                    ],
                    "exchange_wallet": [
                        {
                            "symbol": "BTC",
                            "balance": "2"
                        },
                        {
                            "symbol": "ETH",
                            "balance": "10"
                        }
                    ]
                }
            }
        }
    }

