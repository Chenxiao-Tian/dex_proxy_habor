from typing import Optional
from pydantic import BaseModel, Field


class CancelRequestParams(BaseModel):
    client_request_id: str = Field(
        ...,
        description="ID of the client request to cancel",
        example="abc123"
    )
    gas_price_wei: Optional[int] = Field(
        None,
        description="Optional gas price to use for the cancellation",
        example=1000000000
    )


class CancelRequestResponse(BaseModel):
    tx_hash: str = Field(
        ...,
        description="Transaction hash of the cancellation request",
        example="0xBADF00D"
    )


class CancelRequestSuccess(BaseModel):
    result: CancelRequestResponse       # TODO: WRONG

    model_config = {
        "json_schema_extra": {
            "example": {
                "result": {"tx_hash": "0xBADF00D"}
            }
        }
    }


class CancelRequestErrorDetail(BaseModel):
    code: str = Field(
        ...,
        description="Error code",
        example="TRANSACTION_FAILED"
    )
    message: str = Field(
        ...,
        description="Human-readable error message",
        example="Insufficient funds"
    )


class CancelRequestErrorResponse(BaseModel):
    error: CancelRequestErrorDetail

    model_config = {
        "json_schema_extra": {
            "example": {
                "error": {"code": "TRANSACTION_FAILED", "message": "Insufficient funds"}
            }
        }
    }

