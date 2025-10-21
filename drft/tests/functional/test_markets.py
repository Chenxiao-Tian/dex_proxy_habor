import logging

import pytest

from dex_proxy_api_test_helper import DexProxyApiTestHelper
from common import assert_is_numeric_string, assert_is_int, POSITIVE, NON_NEGATIVE

log = logging.getLogger(__name__)


class TestMarkets:

    @pytest.mark.asyncio
    async def test_get_markets(self, api_helper: DexProxyApiTestHelper):
        """Test /public/markets endpoint."""
        markets_response = await api_helper.get_markets()
        markets_json = await markets_response.json()
        log.info("Markets response: %s", markets_json)

        # Validate HTTP status code
        assert markets_response.status == 200, f"Expected status code 200, got {markets_response.status}"

        # Validate top-level structure
        assert "data" in markets_json, "Response must contain 'data'"
        assert isinstance(markets_json["data"], list), f"'data' must be a list, got {type(markets_json['data'])}"

        # Should contain at least one market
        assert len(markets_json["data"]) > 0, "Response should contain at least one market"

        # Validate each market entry
        for market in markets_json["data"]:
            assert isinstance(market, dict), f"Each market must be a dict, got {type(market)}"

            # Required fields
            required_fields = [
                'base', 'base_currency', 'custom_fields', 'is_active_on_exchange', 'min_order_size',
                'quote_currency', 'raw_response', 'step_order_size', 'tick_size'
            ]
            for field in required_fields:
                assert field in market, f"Market entry must contain '{field}'"

            # Validate base
            base = market['base']
            assert isinstance(base, str), f"'base' must be string, got {type(base)}"
            assert len(base) > 0, "'base' must not be empty"

            # Validate base_currency
            base_currency = market['base_currency']
            assert isinstance(base_currency, str), f"'base_currency' must be string, got {type(base_currency)}"
            assert len(base_currency) > 0, "'base_currency' must not be empty"

            # Validate custom_fields
            custom_fields = market['custom_fields']
            assert isinstance(custom_fields, dict), f"'custom_fields' must be dict, got {type(custom_fields)}"

            # Custom fields should contain specific keys
            custom_required = ['baseDecimals', 'nativeIndex', 'quoteDecimals']
            for cf_field in custom_required:
                assert cf_field in custom_fields, f"'custom_fields' must contain '{cf_field}'"

            # Validate custom_fields values
            assert_is_int(custom_fields['baseDecimals'], 'baseDecimals', POSITIVE)
            assert_is_int(custom_fields['nativeIndex'], 'nativeIndex', NON_NEGATIVE)
            assert_is_int(custom_fields['quoteDecimals'], 'quoteDecimals', POSITIVE)

            # Validate is_active_on_exchange
            is_active = market['is_active_on_exchange']
            assert isinstance(is_active, bool), f"'is_active_on_exchange' must be bool, got {type(is_active)}"

            # Validate min_order_size (positive numeric string)
            assert_is_numeric_string(market['min_order_size'], 'min_order_size', POSITIVE)

            # Validate quote_currency
            quote_currency = market['quote_currency']
            assert isinstance(quote_currency, str), f"'quote_currency' must be string, got {type(quote_currency)}"
            assert len(quote_currency) > 0, "'quote_currency' must not be empty"

            # Validate raw_response
            raw_response = market['raw_response']
            assert isinstance(raw_response, str), f"'raw_response' must be string, got {type(raw_response)}"
            assert len(raw_response) > 0, "'raw_response' must not be empty"

            # Validate step_order_size (positive numeric string)
            assert_is_numeric_string(market['step_order_size'], 'step_order_size', POSITIVE)

            # Validate tick_size (positive numeric string)
            assert_is_numeric_string(market['tick_size'], 'tick_size', POSITIVE)
