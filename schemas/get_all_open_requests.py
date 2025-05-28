from decimal import Decimal
from typing import List, Optional, Union, Literal, Annotated
from pydantic import BaseModel, Field, RootModel


class GetAllOpenRequestsParams(BaseModel):
    request_type: Literal["ORDER", "TRANSFER", "APPROVE", "WRAP_UNWRAP"] = Field(
        ...,
        description="Which type of open requests to fetch",
        example="TRANSFER"
    )


class TransferOpenRequest(BaseModel):
    request_type: Literal["TRANSFER"]
    client_request_id: str
    symbol: str
    amount: Decimal
    address_to: str
    gas_limit: int
    nonce: int
    request_status: Literal["PENDING", "PROCESSING", "COMPLETED", "FAILED"]
    tx_hashes: List[str]
    used_gas_prices_wei: List[int]
    request_path: str
    received_at_ms: int
    finalised_at_ms: Optional[int]


class OrderOpenRequest(BaseModel):
    request_type: Literal["ORDER"]
    client_request_id: str
    order_id: str
    symbol: str
    base_ccy_qty: Decimal
    quote_ccy_qty: Decimal
    side: Literal["BUY", "SELL"]
    exec_price: Optional[Decimal]
    fee_rate: float
    gas_limit: int
    nonce: int
    request_status: Literal["PENDING", "PROCESSING", "COMPLETED", "FAILED"]
    tx_hashes: List[str]
    used_gas_prices_wei: List[int]
    received_at_ms: int
    deadline_since_epoch_s: int
    finalised_at_ms: Optional[int]


class WrapUnwrapOpenRequest(BaseModel):
    request_type: Literal["WRAP_UNWRAP"]
    client_request_id: str
    request: str
    amount: Decimal
    gas_limit: int
    nonce: int
    request_status: Literal["PENDING", "PROCESSING", "COMPLETED", "FAILED"]
    tx_hashes: List[str]
    used_gas_prices_wei: List[int]
    received_at_ms: int
    finalised_at_ms: Optional[int]
    token: str
    token_address: str


class ApproveOpenRequest(BaseModel):
    request_type: Literal["APPROVE"]
    client_request_id: str
    symbol: str
    amount: Decimal
    gas_limit: int
    nonce: int
    request_status: Literal["PENDING", "PROCESSING", "COMPLETED", "FAILED"]
    approve_contract_address: str
    tx_hashes: List[str]
    used_gas_prices_wei: List[int]
    request_path: str
    received_at_ms: int
    finalised_at_ms: Optional[int]


OpenRequest = Annotated[
    Union[
        TransferOpenRequest,
        OrderOpenRequest,
        WrapUnwrapOpenRequest,
        ApproveOpenRequest,
    ],
    Field(discriminator="request_type"),
]


class GetAllOpenRequestsResponse(RootModel[List[OpenRequest]]):
    model_config = {
        "populate_by_name": True
    }

