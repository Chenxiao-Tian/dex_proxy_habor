from decimal import Decimal
from typing import List, Optional, Union, Literal, Annotated
from pydantic import BaseModel, Field, RootModel, ConfigDict


class GetAllOpenRequestsParams(BaseModel):
    request_type: Literal["ORDER", "TRANSFER", "APPROVE", "WRAP_UNWRAP"] = Field(
        ...,
        description="Which type of open requests to fetch",
        example="TRANSFER"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "request_type": "TRANSFER"
            }
        }
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

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "request_type": "TRANSFER",
                "client_request_id": "abc-123",
                "symbol": "ETH",
                "amount": "1.5",
                "address_to": "0xAbCdEf0123456789",
                "gas_limit": 21000,
                "nonce": 5,
                "request_status": "PENDING",
                "tx_hashes": [],
                "used_gas_prices_wei": [1000000000],
                "request_path": "/v1/transfer",
                "received_at_ms": 1620000000000,
                "finalised_at_ms": None
            }
        }
    )


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

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "request_type": "ORDER",
                "client_request_id": "order-123",
                "order_id": "o-456",
                "symbol": "BTC/USDC",
                "base_ccy_qty": "0.1",
                "quote_ccy_qty": "5000.0",
                "side": "BUY",
                "exec_price": None,
                "fee_rate": 0.001,
                "gas_limit": 300000,
                "nonce": 6,
                "request_status": "PROCESSING",
                "tx_hashes": [],
                "used_gas_prices_wei": [2000000000],
                "received_at_ms": 1620001000000,
                "deadline_since_epoch_s": 1620002000,
                "finalised_at_ms": None
            }
        }
    )


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

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "request_type": "WRAP_UNWRAP",
                "client_request_id": "wrap-789",
                "request": "WRAP",
                "amount": "2.0",
                "gas_limit": 25000,
                "nonce": 7,
                "request_status": "COMPLETED",
                "tx_hashes": ["0xTxHashWrap"],
                "used_gas_prices_wei": [1500000000],
                "received_at_ms": 1620003000000,
                "finalised_at_ms": 1620004000000,
                "token": "ETH",
                "token_address": "0xWrapTokenAddress"
            }
        }
    )


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

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "request_type": "APPROVE",
                "client_request_id": "app-321",
                "symbol": "DAI",
                "amount": "1000",
                "gas_limit": 45000,
                "nonce": 8,
                "request_status": "COMPLETED",
                "approve_contract_address": "0xContractAddress",
                "tx_hashes": ["0xTxHashApprove"],
                "used_gas_prices_wei": [1200000000],
                "request_path": "/v1/approve",
                "received_at_ms": 1620005000000,
                "finalised_at_ms": 1620006000000
            }
        }
    )


OpenRequest = Annotated[
    Union[
        TransferOpenRequest,
        OrderOpenRequest,
        WrapUnwrapOpenRequest,
        ApproveOpenRequest,
    ],
    Field(discriminator="request_type"),
]

EXAMPLE_OPEN_REQUESTS = [
    {
        "request_type": "TRANSFER",
        "client_request_id": "abc-123",
        "symbol": "ETH",
        "amount": "1.5",
        "address_to": "0xAbCdEf0123456789",
        "gas_limit": 21000,
        "nonce": 5,
        "request_status": "PENDING",
        "tx_hashes": [],
        "used_gas_prices_wei": [1000000000],
        "request_path": "/v1/transfer",
        "received_at_ms": 1620000000000,
        "finalised_at_ms": None
    },
    {
        "request_type": "ORDER",
        "client_request_id": "order-123",
        "order_id": "o-456",
        "symbol": "BTC/USDC",
        "base_ccy_qty": "0.1",
        "quote_ccy_qty": "5000.0",
        "side": "BUY",
        "exec_price": None,
        "fee_rate": 0.001,
        "gas_limit": 300000,
        "nonce": 6,
        "request_status": "PROCESSING",
        "tx_hashes": [],
        "used_gas_prices_wei": [2000000000],
        "received_at_ms": 1620001000000,
        "deadline_since_epoch_s": 1620002000,
        "finalised_at_ms": None
    }
]

class GetAllOpenRequestsResponse(BaseModel):
    requests: List[OpenRequest]

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "example": {
                "requests": EXAMPLE_OPEN_REQUESTS
            }
        }
    )
