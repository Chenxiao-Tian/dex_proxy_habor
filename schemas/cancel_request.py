from typing import Optional
from pydantic import BaseModel, Field


class CancelRequestParams(BaseModel):
    client_request_id: str = Field(
        ...,
        description="ID of the client request to cancel",
        example="abc123"
    )

class CancelResult(BaseModel):
    tx_hash: Optional[str]

class CancelSuccessResponse(BaseModel):
    result: CancelResult
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "result": {
                    "tx_hash": "123"
                }
            }
        }
    }
