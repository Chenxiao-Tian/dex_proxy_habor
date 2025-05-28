from typing import List, Literal
from pydantic import BaseModel, Field


class CancelAllParams(BaseModel):
    """
    Query/body parameters for DELETE /private/cancel-all
    """
    request_type: Literal["ORDER", "TRANSFER", "APPROVE", "WRAP_UNWRAP"] = Field(
        ...,
        description="Which type of open requests to cancel",
        example="TRANSFER",
    )


class CancelAllResponse(BaseModel):
    """
    Successful response for DELETE /private/cancel-all
    """
    cancel_requested: List[str] = Field(
        ...,
        description="List of client_request_id values for which cancel was requested"
    )
    failed_cancels: List[str] = Field(
        ...,
        description="List of client_request_id values for which cancel failed"
    )

    class Config:
        model_config = {
            "json_schema_extra": {
                "example": {
                    "cancel_requested": ["req1", "req2"],
                    "failed_cancels": ["req3"]
                }
            }
        }


class ErrorResponse(BaseModel):
    """
    Error response payload
    """
    error: dict = Field(
        ...,
        description="Error message",
        example={"message": "Unknown transaction type"}
    )

