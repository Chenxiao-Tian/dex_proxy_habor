
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, Field

CLIENT_REQUEST_ID_FIELD = Field(
    ...,
    description="Client request identifier",
    example="1726470823456789123",
)
SYMBOL_FIELD = Field(
    ...,
    description="Token symbol",
    example="USDC",
)
AMOUNT_FIELD = Field(
    ...,
    description="Quantity",
    example="1.5",
)
GAS_PRICE_WEI_FIELD = Field(
    ...,
    description="Gas price in wei for the on-chain transaction",
    example=25_000_000_000,
)
GAS_LIMIT_FIELD = Field(
    ...,
    description="Gas limit for the on-chain transaction",
    example=500_000,
)
DEPOSIT_GAS_PRICE_FIELD = Field(
    ...,
    alias="gas_price",
    description="Gas price in wei for the on-chain transaction",
    example=25_000_000_000,
)
ADDRESS_TO_FIELD = Field(
    None,
    description="Destination address (optional)",
    example="0x1234567890abcdef1234567890abcdef12345678",
)


class TxResponse(BaseModel):
    tx_hash: str = Field(..., description="Transaction hash on success")


class ApproveTokenRequest(BaseModel):
    client_request_id: str = CLIENT_REQUEST_ID_FIELD
    symbol: str = SYMBOL_FIELD
    amount: Decimal = AMOUNT_FIELD
    gas_price_wei: int = GAS_PRICE_WEI_FIELD
    gas_limit: int = GAS_LIMIT_FIELD

    class Config:
        json_encoders = {Decimal: lambda v: str(v)}
        schema_extra = {
            "example": {
                "client_request_id": "1726470823456789123",
                "symbol": "USDC",
                "amount": "1.5",
                "gas_price_wei": 25000000000,
                "gas_limit": 500000
            }
        }


class WithdrawRequest(BaseModel):
    client_request_id: str = CLIENT_REQUEST_ID_FIELD
    symbol: str = SYMBOL_FIELD
    amount: Decimal = AMOUNT_FIELD

    class Config:
        json_encoders = {Decimal: lambda v: str(v)}
        schema_extra = {
            "example": {
                "client_request_id": "1726470823456789123",
                "symbol": "USDC",
                "amount": "1.5"
            }
        }


class DepositRequest(BaseModel):
    client_request_id: str = CLIENT_REQUEST_ID_FIELD
    symbol: str = SYMBOL_FIELD
    amount: Decimal = AMOUNT_FIELD
    gas_limit: int = GAS_LIMIT_FIELD
    gas_price_wei: int = DEPOSIT_GAS_PRICE_FIELD

    class Config:
        json_encoders = {Decimal: lambda v: str(v)}
        schema_extra = {
            "example": {
                "client_request_id": "1726470823456789123",
                "symbol": "USDC",
                "amount": "1.5",
                "gas_limit": 500000,
                "gas_price": 25000000000
            }
        }


class TransferParams(BaseModel):
    client_request_id: str = CLIENT_REQUEST_ID_FIELD
    symbol: str = SYMBOL_FIELD
    amount: Decimal = AMOUNT_FIELD
    gas_limit: int = GAS_LIMIT_FIELD
    gas_price_wei: int = GAS_PRICE_WEI_FIELD
    address_to: Optional[str] = ADDRESS_TO_FIELD

    class Config:
        json_encoders = {Decimal: lambda v: str(v)}
        schema_extra = {
            "example": {
                "client_request_id": "1726470823456789123",
                "symbol": "USDC",
                "amount": "1.5",
                "gas_limit": 500000,
                "gas_price_wei": 25000000000,
                "address_to": "0x1234567890abcdef1234567890abcdef12345678"
            }
        }


class TransferResponse(BaseModel):
    tx_hash: str = Field(..., description="Transaction hash on success")
