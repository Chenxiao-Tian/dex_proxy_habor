import logging

import pytest

from dex_proxy_api_test_helper import DexProxyApiTestHelper
from common import assert_is_numeric_string, assert_is_number, POSITIVE, NON_NEGATIVE

log = logging.getLogger(__name__)


class TestContractData:

    @pytest.mark.asyncio
    async def test_get_contract_data(self, api_helper: DexProxyApiTestHelper):
        """Test /public/contract-data endpoint."""
        contract_data_response = await api_helper.get_contract_data()
        contract_data_json = await contract_data_response.json()
        log.info("Contract data response: %s", contract_data_json)

        # Validate HTTP status code
        assert contract_data_response.status == 200, f"Expected status code 200, got {contract_data_response.status}"

        # Validate top-level structure is a dictionary
        assert isinstance(contract_data_json, dict), f"Response must be a dict, got {type(contract_data_json)}"

        # Should contain at least one market
        assert len(contract_data_json) > 0, "Response should contain at least one market"

        # Validate each market's contract data
        for market_symbol, market_data in contract_data_json.items():
            # Validate market symbol format
            assert isinstance(market_symbol, str), f"Market symbol must be string, got {type(market_symbol)}"
            assert len(market_symbol) > 0, "Market symbol must not be empty"

            # Validate market_data is a dict
            assert isinstance(market_data, dict), (
                f"Market data for {market_symbol} must be dict, got {type(market_data)}"
            )

            # Validate required fields
            required_fields = [
                'funding_rate', 'index_price', 'mark_price', 'next_funding_rate',
                'next_funding_rate_timestamp', 'open_interest'
            ]
            for field in required_fields:
                assert field in market_data, f"Market data for {market_symbol} must contain '{field}'"

            # Validate index_price (string, positive)
            assert_is_numeric_string(market_data['index_price'], 'index_price', POSITIVE)

            #if market_symbol in ["SOL", "mSOL", "wBTC", "wETH", "USDT", "jitoSOL"]:
            if market_data['funding_rate'] == "N/A":
                # Skip further validation for markets with 'N/A' funding rate
                continue

            # Validate funding_rate (string representation of decimal)
            assert_is_numeric_string(market_data['funding_rate'], 'funding_rate')

            # Validate mark_price (numeric)
            assert_is_number(market_data['mark_price'], f"'mark_price' for {market_symbol}", POSITIVE)

            # Validate next_funding_rate (string, numeric)
            assert_is_numeric_string(market_data['next_funding_rate'], 'next_funding_rate')

            # Validate next_funding_rate_timestamp (string milliseconds)
            assert_is_numeric_string(market_data['next_funding_rate_timestamp'], 'next_funding_rate_timestamp')

            # Validate open_interest (string, non-negative)
            assert_is_numeric_string(market_data['open_interest'], 'open_interest', NON_NEGATIVE)
