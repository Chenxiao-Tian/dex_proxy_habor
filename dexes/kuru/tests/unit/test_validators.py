from typing import cast
import pytest
from kuru_sdk.types import OrderRequest as KuruOrderRequest

from dexes.kuru.handler.schemas import CreateOrderIn, OrderSide, OrderType, OrderIn
from dexes.kuru.handler.validators import validate_and_map_to_kuru_order_request, validate_order_request, ValidationError
from schemas import CreateOrderRequest


class TestValidateAndMapToKuruOrderRequest:
    """Tests for the validate_and_map_to_kuru_order_request function."""

    @pytest.mark.parametrize(
        "order_input_params, post_creation_modifiers, expected_order_request, expected_error",
        [
            pytest.param(
                {"price": "100", "quantity": "10", "client_order_id": "123", "side": OrderSide.BUY, "order_type": OrderType.LIMIT, "symbol": "TEST_MARKET"},
                None,
                KuruOrderRequest(market_address="TEST_MARKET", order_type="limit", side="buy", price="100", size="10", post_only=False),
                None,
                id="valid_limit_buy_order"
            ),
            pytest.param(
                {"price": "200", "quantity": "20", "client_order_id": "456", "side": OrderSide.BUY, "order_type": OrderType.LIMIT_POST_ONLY, "symbol": "TEST_MARKET"},
                None,
                KuruOrderRequest(market_address="TEST_MARKET", order_type="limit", side="buy", price="200", size="20", post_only=True),
                None,
                id="valid_limit_post_only_buy_order"
            ),
            pytest.param(
                {"price": "", "quantity": "30", "client_order_id": "789", "side": OrderSide.BUY, "order_type": OrderType.MARKET, "symbol": "TEST_MARKET"},
                None,
                KuruOrderRequest(market_address="TEST_MARKET", order_type="market", side="buy", price="", size="30", post_only=False),
                None,
                id="valid_market_buy_order"
            ),
            pytest.param(
                {"price": "250", "quantity": "15", "client_order_id": "999", "side": OrderSide.SELL, "order_type": OrderType.LIMIT, "symbol": "TEST_MARKET"},
                None,
                KuruOrderRequest(market_address="TEST_MARKET", order_type="limit", side="sell", price="250", size="15", post_only=False),
                None,
                id="valid_limit_sell_order"
            ),
            pytest.param(
                {"price": "", "quantity": "40", "client_order_id": "012", "side": OrderSide.BUY, "order_type": OrderType.LIMIT, "symbol": "TEST_MARKET"},
                None,
                None,
                ["Price is required for limit orders."],
                id="invalid_limit_buy_missing_price"
            ),
            pytest.param(
                {"price": "300", "quantity": "", "client_order_id": "345", "side": OrderSide.BUY, "order_type": OrderType.LIMIT, "symbol": "TEST_MARKET"},
                None,
                None,
                ["Quantity/Size is required."],
                id="invalid_limit_buy_missing_quantity"
            ),
            pytest.param(
                {"price": "", "quantity": "", "client_order_id": "567", "side": OrderSide.BUY, "order_type": OrderType.LIMIT, "symbol": "TEST_MARKET"},
                None,
                None,
                ["Price is required for limit orders.", "Quantity/Size is required."],
                id="invalid_limit_buy_missing_price_quantity"
            ),
            pytest.param(
                {"price": "400", "quantity": "50", "client_order_id": "678", "side": OrderSide.BUY, "order_type": OrderType.LIMIT, "symbol": "TEST_MARKET"},
                [("order_type", "INVALID_TYPE")],
                None,
                ["Invalid order type: INVALID_TYPE"],
                id="invalid_order_type_string"
            ),
            pytest.param(
                {"price": "400", "quantity": "50", "client_order_id": "678", "side": OrderSide.BUY, "order_type": OrderType.LIMIT, "symbol": "TEST_MARKET"},
                [("side", "INVALID_SIDE")],
                None,
                ["Invalid order side: INVALID_SIDE"],
                id="invalid_order_side_string"
            ),
            pytest.param(
                {"price": "", "quantity": "", "client_order_id": "678", "side": OrderSide.BUY, "order_type": OrderType.LIMIT, "symbol": "TEST_MARKET"},
                [("order_type", "INVALID_TYPE")],
                None,
                ["Invalid order type: INVALID_TYPE", "Price is required for limit orders.", "Quantity/Size is required."],
                id="invalid_type_missing_price_quantity"
            ),
            pytest.param(
                {"price": "100", "quantity": "10", "client_order_id": "678", "side": OrderSide.BUY, "order_type": OrderType.LIMIT, "symbol": "TEST_MARKET"},
                [("order_type", "INVALID_TYPE"), ("side", "INVALID_SIDE")],
                None,
                ["Invalid order type: INVALID_TYPE", "Invalid order side: INVALID_SIDE"],
                id="invalid_type_and_side_strings"
            ),
            pytest.param(
                {"price": "", "quantity": "", "client_order_id": "1234", "side": OrderSide.BUY, "order_type": OrderType.LIMIT, "symbol": "TEST_MARKET"},
                [("order_type", "INVALID_TYPE"), ("side", "INVALID_SIDE")],
                None,
                ["Invalid order type: INVALID_TYPE", "Invalid order side: INVALID_SIDE", "Price is required for limit orders.", "Quantity/Size is required."],
                id="all_errors_invalid_type_side_missing_price_quantity"
            ),
        ]
    )
    def test_validate_and_map_to_kuru_order_request(self, order_input_params, post_creation_modifiers, expected_order_request, expected_error):
        """
        Test validate_and_map_to_kuru_order_request function with different inputs.
        
        The function should correctly map valid inputs to OrderRequest objects
        and raise appropriate errors for invalid inputs.
        """
        order_input = CreateOrderRequest(**order_input_params)

        if post_creation_modifiers:
            for attr, value in post_creation_modifiers:
                setattr(order_input, attr, value)

        if expected_error:
            with pytest.raises(ValidationError) as excinfo:
                validate_and_map_to_kuru_order_request(order_input)
            assert set(excinfo.value.args[0]) == set(expected_error)
        else:
            result = validate_and_map_to_kuru_order_request(order_input)
            
            assert isinstance(result, KuruOrderRequest)
            
            assert result.market_address == expected_order_request.market_address
            assert result.order_type == expected_order_request.order_type
            assert result.side == expected_order_request.side
            assert result.price == expected_order_request.price
            assert result.size == expected_order_request.size
            assert result.post_only == expected_order_request.post_only


class TestValidateOrderRequest:
    """Tests for the validate_order_request function."""
    
    @pytest.mark.parametrize(
        "order_input, expected_result, expected_error_message",
        [
            pytest.param(
                {"client_order_id": "123"},
                "123",
                None,
                id="valid_small_positive_integer"
            ),
            pytest.param(
                {"client_order_id": "999999999"},
                "999999999",
                None,
                id="valid_large_positive_integer"
            ),
            pytest.param(
                cast(OrderIn, {}),
                None,
                "client_order_id is required",
                id="invalid_missing_client_order_id"
            ),
            pytest.param(
                {"client_order_id": ""},
                None,
                "client_order_id cannot be empty",
                id="invalid_empty_client_order_id"
            ),
            pytest.param(
                {"client_order_id": "-1"},
                None,
                "client_order_id must be a positive integer",
                id="invalid_negative_client_order_id"
            ),
            pytest.param(
                {"client_order_id": "0"},
                None,
                "client_order_id must be a positive integer",
                id="invalid_zero_client_order_id"
            ),
            pytest.param(
                {"client_order_id": "abc"},
                None,
                "client_order_id must be a valid integer",
                id="invalid_non_numeric_client_order_id"
            ),
            pytest.param(
                {"client_order_id": "123.45"},
                None,
                "client_order_id must be a valid integer",
                id="invalid_float_client_order_id"
            ),
        ]
    )
    def test_validate_order_request(self, order_input, expected_result, expected_error_message):
        if expected_error_message:
            with pytest.raises(ValidationError) as exc_info:
                validate_order_request(order_input)
            assert expected_error_message in str(exc_info.value)
        else:
            result = validate_order_request(order_input)
            assert result == expected_result
