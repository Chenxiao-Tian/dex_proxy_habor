from decimal import Decimal
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field, ConfigDict

from py_dex_common.schemas import QueryOrderResponse

class QueryLiveOrdersResponse(BaseModel):
    send_timestamp_ns: int = Field(..., example=1620000001000000000)
    orders: List[QueryOrderResponse] = Field(..., example=[])

    model_config = {
        "json_schema_extra": {
            "example": {
                "send_timestamp_ns": 1620000001000000000,
                "orders": [
                    {
                        "client_order_id": "123",
                        "order_id": "456",
                        "price": "50000.0",
                        "quantity": "0.1",
                        "total_exec_quantity": "0.05",
                        "last_update_timestamp_ns": 1620000000000000000,
                        "status": "FILLED",
                        "reason": None,
                        "trades": [],
                        "order_type": "LIMIT",
                        "symbol": "BTC/USDC",
                        "side": "BUY",
                        "place_tx_sig": "0xSIG",
                        "send_timestamp_ns": 1620000001000000000
                    }
                ]
            }
        }
    }

