from pydantic import BaseModel, Field


class AmendRequestParams(BaseModel):
    """
    Body parameters for POST /private/amend-request
    """
    client_request_id: str = Field(
        ...,
        description="ID of the client request to amend",
        example="abc123"
    )
    gas_price_wei: int = Field(
        ...,
        description="Gas price to use for the amendment",
        example=1000000000
    )


class AmendRequestResult(BaseModel):
    """
    Payload returned on a successful amend
    """
    tx_hash: str = Field(
        ...,
        description="Transaction hash of the amend request",
        example="0xCAFEBABE"
    )


class AmendRequestSuccess(BaseModel):
    """
    200 OK response model
    """
    result: AmendRequestResult

    model_config = {
        "json_schema_extra": {
            "example": {
                "result": {
                    "tx_hash": "0xCAFEBABE"
                }
            }
        }
    }


class AmendRequestErrorResponse(BaseModel):
    """
    Error response model (400, 404, etc.)
    """
    error: dict = Field(
        ...,
        description="Error code and/or message",
        example={"message": "request not found"}
    )

