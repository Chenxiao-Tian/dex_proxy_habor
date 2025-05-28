# schemas_request_status.py

from decimal import Decimal
from typing import List, Optional, Literal
from pydantic import BaseModel, Field


class GetRequestStatusParams(BaseModel):
    """
    Query parameters for GET /public/get-request-status
    """
    client_request_id: str = Field(
        ...,
        description="ID of the client request to look up",
        example="abc123"
    )


class GetRequestStatusResponse(BaseModel):
    """
    Successful response for GET /public/get-request-status
    """
    client_request_id: str
    symbol: str
    amount: Decimal
    gas_limit: int
    nonce: int
    request_type: Literal["ORDER", "TRANSFER", "APPROVE", "WRAP_UNWRAP"]
    request_status: Literal["PENDING", "PROCESSING", "COMPLETED", "FAILED"]
    approve_contract_address: Optional[str] = None
    tx_hashes: List[str]
    used_gas_prices_wei: List[int]
    request_path: Optional[str] = None
    received_at_ms: int
    finalised_at_ms: Optional[int] = None


class ErrorResponse(BaseModel):
    """
    Error response payload
    """
    error: dict = Field(
        ...,
        example={"message": "Request not found"}
    )

