from decimal import Decimal
from typing import List, Optional, Literal
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
    default=None,
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
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "tx_hash": "0x123"
            }
        }
    }
    

class ApproveTokenRequest(BaseModel):
    client_request_id: str = CLIENT_REQUEST_ID_FIELD
    symbol: str = SYMBOL_FIELD
    amount: Decimal = AMOUNT_FIELD
    gas_price_wei: int = GAS_PRICE_WEI_FIELD
    gas_limit: Optional[int] = GAS_LIMIT_FIELD

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
        
class WrapUnwrapRequest(BaseModel):
    client_request_id: str = CLIENT_REQUEST_ID_FIELD
    symbol: str = SYMBOL_FIELD
    amount: Decimal = AMOUNT_FIELD
    type: Literal[
        "wrap",
        "unwrap"
    ] = Field(..., example="wrap")
    gas_price_wei: int = GAS_PRICE_WEI_FIELD
    gas_limit: int = GAS_LIMIT_FIELD

    class Config:
        json_encoders = {Decimal: lambda v: str(v)}
        schema_extra = {
            "example": {
                "client_request_id": "1726470823456789123",
                "symbol": "ETH",
                "amount": "1.5",
                "type": "wrap",
                "gas_price_wei": 25000000000,
                "gas_limit": 500000
            }
        }
        
class ExchangeTransferRequest(BaseModel):
    client_request_id: str = CLIENT_REQUEST_ID_FIELD
    symbol: str = SYMBOL_FIELD
    amount: Decimal = AMOUNT_FIELD
    src_account: str = Field(..., example="accountA")
    dest_account: str = Field(..., example="accountB")
    gas_price_wei: int = GAS_PRICE_WEI_FIELD
    gas_limit: int = GAS_LIMIT_FIELD

    class Config:
        json_encoders = {Decimal: lambda v: str(v)}
        schema_extra = {
            "example": {
                "client_request_id": "1726470823456789123",
                "symbol": "USDC",
                "amount": "1.5",
                "src_account": "accountA",
                "dest_account": "accountB",
                "gas_price_wei": 25000000000,
                "gas_limit": 500000
            }
        }

class DepositIntoExchangeRequest(BaseModel):
    client_order_id: str = Field(..., example="123")
    symbol: str = Field(
        ...,
        description="Token symbol to deposit",
        example="SOL"
    )
    amount: Decimal = Field(
        ...,
        description="Amount of token to deposit",
        example="1.234"
    )
    gas_limit: int = Field(..., example="123")
    gas_price_wei: int = Field(..., example="123")
    
    class Config:
        json_encoders = {Decimal: lambda v: str(v)}
        schema_extra = {
            "example": {
                "client_request_id": "1726470823456789123",
                "symbol": "ETH",
                "amount": "1.5",
                "gas_price_wei": 25000000000,
                "gas_limit": 500000
            }
        }


class WithdrawFromExchangeRequest(BaseModel):
    client_order_id: str = Field(..., example="123")
    symbol: str = Field(
        ...,
        description="Token symbol to withdraw",
        example="SOL"
    )
    amount: Decimal = Field(
        ...,
        description="Amount of token to withdraw",
        example="1.234"
    )
    gas_limit: int = Field(..., example="123")
    gas_price_wei: int = Field(..., example="123")
    
    class Config:
        json_encoders = {Decimal: lambda v: str(v)}
        schema_extra = {
            "example": {
                "client_request_id": "1726470823456789123",
                "symbol": "ETH",
                "amount": "1.5",
                "gas_price_wei": 25000000000,
                "gas_limit": 500000
            }
        }




