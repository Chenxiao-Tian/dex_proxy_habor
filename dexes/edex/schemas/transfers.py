from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, Field


class DepositRequest(BaseModel):
    token: str = Field(
        ...,
        description="Token symbol to deposit",
        example="SOL"
    )
    amount: Decimal = Field(
        ...,
        description="Amount of token to deposit",
        example="1.234"
    )


class WithdrawRequest(BaseModel):
    token: str = Field(
        ...,
        description="Token symbol to withdraw",
        example="SOL"
    )
    amount: Decimal = Field(
        ...,
        description="Amount of token to withdraw",
        example="0.5"
    )


class TxSigResponse(BaseModel):
    tx_sig: str = Field(
        ...,
        description="Signature of the submitted transaction",
        example="0xCAFEBABE"
    )

    model_config = {
        "json_schema_extra": {
            "example": {"tx_sig": "0xCAFEBABE"}
        }
    }


class DepositErrorResponse(BaseModel):
    error: str = Field(
        ...,
        description="Error message when deposit fails",
        example="Invalid token"
    )

    model_config = {
        "json_schema_extra": {
            "example": {"error": "Invalid token"}
        }
    }


class WithdrawErrorResponse(BaseModel):
    error: str = Field(
        ...,
        description="Error message when withdraw fails",
        example="Invalid token"
    )

    model_config = {
        "json_schema_extra": {
            "example": {"error": "Invalid token"}
        }
    }


class TransactionFailedResponse(BaseModel):
    status: str = Field(
        ...,
        description="Status message when transaction fails on-chain",
        example="Transaction failed"
    )

    model_config = {
        "json_schema_extra": {
            "example": {"status": "Transaction failed"}
        }
    }


class BalanceItem(BaseModel):
    symbol: str = Field(..., example="SOL")
    mint: str = Field(..., example="So11111111111111111111111111111111111111112")
    decimals: int = Field(..., example=9)
    status: str = Field(..., example="active")
    balance: Decimal = Field(..., example="0.5")


class BalanceResponse(BaseModel):
    success: bool = Field(
        ...,
        description="Whether the balance query succeeded",
        example=True
    )
    perp_pnl: Decimal = Field(
        ...,
        description="Unrealized PnL for perpetual positions",
        example="0.123"
    )
    balances: List[BalanceItem] = Field(
        ...,
        description="List of spot account balances"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "success": True,
                "perp_pnl": "0.123",
                "balances": [
                    {
                        "symbol": "SOL",
                        "mint": "So11111111111111111111111111111111111111112",
                        "decimals": 9,
                        "status": "active",
                        "balance": "0.5"
                    }
                ]
            }
        }
    }

