from typing import Optional
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
    subaccount: int = Field(
        ...,
        description="Subaccount identifier",
        example=0
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
                    "subaccount": 0,
                    "enabled": True,
                    "tx_sig": "0xabc123"
                },
                "disable_success": {
                    "account": "alice",
                    "subaccount": 0,
                    "enabled": False,
                    "tx_sig": "0xdef456"
                },
                "error": {
                    "account": "alice",
                    "subaccount": 0,
                    "failure": "Insufficient margin"
                }
            }
        }
    }
