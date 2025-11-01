from typing import Optional
from pydantic import BaseModel, Field


class InitializeUserResponse(BaseModel):
    """
    Response model for POST /private/initialize-user
    """
    account: str = Field(
        ...,
        description="The main account identifier",
        example="alice"
    )
    subaccount: int = Field(
        ...,
        description="The subaccount identifier",
        example=0
    )
    tx_sig: Optional[str] = Field(
        None,
        description="Transaction signature if a new initialization was performed",
        example="0xabc123"
    )
    failure: Optional[str] = Field(
        None,
        description="Error message if initialization failed",
        example="already in use"
    )

    model_config = {
        "json_schema_extra": {
            "examples": {
                "success": {
                    "account": "alice",
                    "subaccount": 0,
                    "tx_sig": "0xabc123"
                },
                "already_initialized": {
                    "account": "alice",
                    "subaccount": 0
                },
                "error": {
                    "account": "alice",
                    "subaccount": 0,
                    "failure": "some unexpected error"
                }
            }
        }
    }
