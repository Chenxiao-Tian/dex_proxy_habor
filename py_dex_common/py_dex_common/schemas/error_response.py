from enum import IntEnum
from typing import Optional
from pydantic import BaseModel, Field


class ErrorType(IntEnum):
    NO_ERROR = 0
    TRANSACTION_REVERTED = 1
    TRANSACTION_TIMED_OUT = 2
    TRANSACTION_FAILED = 3


class ErrorDetail(BaseModel):
    code: Optional[ErrorType] = Field(
        ...,
        description="Numeric error code",
        example=1
    )
    message: str = Field(
        ...,
        description="Human-readable error message",
        example="Gas too low"
    )


class ErrorResponse(BaseModel):
    error: ErrorDetail

    model_config = {
        "json_schema_extra": {
            "example": {
                "error": {
                    "code": 1,
                    "message": "Gas too low"
                }
            }
        }
    }


