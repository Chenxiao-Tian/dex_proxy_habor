from typing import Any, Dict, List
from pydantic import BaseModel, Field


class QueryPortfolioResponse(BaseModel):
    send_timestamp_ns: int = Field(
        ...,
        example=1620000001000000000,
        description="Timestamp (ns since epoch) when portfolio was retrieved",
    )
    spot_positions: List[Dict[str, Any]] = Field(
        ...,
        description="List of spot positions; schema depends on the specific DEX implementation",
        example=[],
    )
    perp_positions: List[Dict[str, Any]] = Field(
        ...,
        description="List of perpetual positions; schema depends on the specific DEX implementation",
        example=[],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "send_timestamp_ns": 1620000001000000000,
                "spot_positions": [],
                "perp_positions": [],
            }
        }
    }
