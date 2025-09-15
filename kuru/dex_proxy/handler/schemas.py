from enum import Enum
from typing import Literal

class KuruErrorCode(str, Enum):
    EXCHANGE_REJECTION = "EXCHANGE_REJECTION"
    INVALID_PARAMETER = "INVALID_PARAMETER"
    ORDER_NOT_FOUND = "ORDER_NOT_FOUND"

class KuruOrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    LIMIT_POST_ONLY = "LIMIT_POST_ONLY"

class KuruOrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class KuruOrderStatus(str, Enum):
    OPEN = "OPEN"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    # TODO: This status should be deleted in favour of CANCELLED
    CANCELLED_PENDING = "CANCELLED_PENDING"
    REJECTED = "REJECTED"

# Legacy aliases for backward compatibility
ErrorCode = KuruErrorCode
OrderType = KuruOrderType
OrderSide = KuruOrderSide
OrderStatus = KuruOrderStatus

# Conversion functions for mapping to py_dex_common standard values
def kuru_order_side_to_common(kuru_side: KuruOrderSide) -> Literal["BUY", "SELL"]:
    """Convert Kuru order side to py_dex_common standard format"""
    return kuru_side.value  # type: ignore

def kuru_order_type_to_common(kuru_type: KuruOrderType) -> str:
    """Convert Kuru order type to py_dex_common standard format"""
    return kuru_type.value

def kuru_order_status_to_common(kuru_status: KuruOrderStatus) -> str:
    """Convert Kuru order status to py_dex_common standard format"""
    return kuru_status.value

def kuru_error_code_to_common(kuru_error: KuruErrorCode) -> str:
    """Convert Kuru error code to py_dex_common standard format"""
    return kuru_error.value
