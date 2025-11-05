import logging

import pytest

from dex_proxy_api_test_helper import DexProxyApiTestHelper
from common import assert_is_int, assert_is_number, NON_NEGATIVE

log = logging.getLogger(__name__)


class TestMarginData:

    @pytest.mark.asyncio
    async def test_get_margin_data(self, api_helper: DexProxyApiTestHelper):
        """Test /public/margin-data endpoint."""
        margin_data_response = await api_helper.get_margin_data()
        margin_data_json = await margin_data_response.json()
        log.info("Margin data response: %s", margin_data_json)

        # Validate HTTP status code
        assert margin_data_response.status == 200, f"Expected status code 200, got {margin_data_response.status}"

        # Validate required top-level fields
        required_fields = [
            'available_margin', 'maintenance_margin', 'maintenance_ratio', 'perp_positions',
            'total_collateral', 'total_equity', 'upnl'
        ]
        for field in required_fields:
            assert field in margin_data_json, f"Response must contain '{field}'"

        # Validate available_margin
        assert_is_number(margin_data_json['available_margin'], 'available_margin')

        # Validate maintenance_margin
        assert_is_number(margin_data_json['maintenance_margin'], 'maintenance_margin', NON_NEGATIVE)

        # Validate maintenance_ratio
        assert_is_number(margin_data_json['maintenance_ratio'], 'maintenance_ratio')

        # Validate total_collateral
        assert_is_number(margin_data_json['total_collateral'], 'total_collateral', NON_NEGATIVE)

        # Validate total_equity
        assert_is_number(margin_data_json['total_equity'], 'total_equity')

        # Validate upnl (unrealized P&L)
        assert_is_number(margin_data_json['upnl'], 'upnl')

        # Validate perp_positions is a list
        perp_positions = margin_data_json['perp_positions']
        assert isinstance(perp_positions, list), f"'perp_positions' must be a list, got {type(perp_positions)}"

        # Validate each position in perp_positions
        for position in perp_positions:
            assert isinstance(position, dict), f"Each position must be a dict, got {type(position)}"

            # Required fields in each position
            position_fields = [
                'entry_price', 'market', 'market_index', 'name', 'pnl', 'size', 'size_usd', 'unrealized_pnl'
            ]
            for field in position_fields:
                assert field in position, f"Position must contain '{field}'"

            # Validate entry_price
            assert_is_number(position['entry_price'], 'entry_price')

            # Validate market
            assert_is_int(position['market'], 'market', NON_NEGATIVE)

            # Validate market_index
            assert_is_int(position['market_index'], 'market_index', NON_NEGATIVE)

            # Validate name (market symbol)
            name = position['name']
            assert isinstance(name, str), f"'name' must be string, got {type(name)}"
            assert len(name) > 0, "'name' must not be empty"

            # Validate pnl
            assert_is_number(position['pnl'], 'pnl')

            # Validate size
            assert_is_number(position['size'], 'size')

            # Validate size_usd
            assert_is_number(position['size_usd'], 'size_usd', NON_NEGATIVE)

            # Validate unrealized_pnl
            assert_is_number(position['unrealized_pnl'], 'unrealized_pnl')
