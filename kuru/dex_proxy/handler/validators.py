from kuru_sdk.types import OrderRequest

from py_dex_common.schemas import CreateOrderRequest, QueryOrderParams, CancelOrderParams
from .schemas import OrderType, OrderSide

class ValidationError(Exception):
    pass

def validate_order_request(order_input) -> str:
    """
    Validate order request parameters and return the client_order_id as string.
    
    Args:
        order_input: Object with client_order_id attribute (QueryOrderParams or CancelOrderParams)
        
    Returns:
        str: The validated client_order_id as string
        
    Raises:
        ValidationError: If validation fails
    """
    errors = []
    
    if not hasattr(order_input, 'client_order_id') or order_input.client_order_id is None:
        errors.append("client_order_id is required")
    else:
        client_order_id = order_input.client_order_id
        
        if not client_order_id:
            errors.append("client_order_id cannot be empty")
        else:
            # Try to convert to integer to validate it's a positive integer
            try:
                client_order_id_int = int(client_order_id)
                if client_order_id_int <= 0:
                    errors.append("client_order_id must be a positive integer")
            except (ValueError, TypeError):
                errors.append("client_order_id must be a valid integer")
    
    if errors:
        raise ValidationError(errors)
    
    return str(order_input.client_order_id)

def validate_and_map_to_kuru_order_request(order_input: CreateOrderRequest) -> OrderRequest:
    errors = []
    kuru_order_type = "limit"  # Default to a valid value
    post_only_flag: bool = False

    input_order_type = order_input.order_type
    if input_order_type == "LIMIT":
        kuru_order_type = "limit"
    elif input_order_type == "LIMIT_POST_ONLY":
        kuru_order_type = "limit"
        post_only_flag = True
    elif input_order_type == "MARKET":
        kuru_order_type = "market"
    else:
        errors.append(f"Invalid order type: {input_order_type}")
    
    # Map the side to lowercase for Kuru SDK
    kuru_side = "buy"
    if order_input.side == "BUY":
        kuru_side = "buy"
    elif order_input.side == "SELL":
        kuru_side = "sell"
    else:
        errors.append(f"Invalid order side: {order_input.side}")
            
    if not order_input.price and kuru_order_type != "market":
        errors.append("Price is required for limit orders.")
    
    if not order_input.quantity:
        errors.append("Quantity/Size is required.")

    if errors:
        raise ValidationError(errors)
    
    order_request = OrderRequest(
        market_address=order_input.symbol,
        order_type=kuru_order_type,
        side=kuru_side,
        price=order_input.price,
        size=order_input.quantity,
        post_only=post_only_flag,
    )

    return order_request