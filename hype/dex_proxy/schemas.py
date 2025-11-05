from pydantic import BaseModel, Field

class UpdateLeverageRequest(BaseModel):
    coin: str = Field(
        ...,
        description="Symbol of the asset whose leverage is to be updated"
    )
    is_cross: bool = Field(
        ...,
        description="True for cross margin, False for isolated"
    )
    leverage: int = Field(
        ...,
        description="Desired leverage (integer)"
    )

class UpdateLeverageResponse(BaseModel):
    tx_hash: str = Field(
        ...,
        description="Transaction hash of the leverage-update operation"
    )

