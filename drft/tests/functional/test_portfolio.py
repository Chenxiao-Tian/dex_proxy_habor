import logging

import pytest

from dex_proxy_api_test_helper import DexProxyApiTestHelper
from common import assert_is_number, NON_NEGATIVE

log = logging.getLogger(__name__)


class TestPortfolio:

    @pytest.mark.asyncio
    async def test_get_portfolio(self, api_helper: DexProxyApiTestHelper):
        """Test /public/portfolio endpoint."""
        portfolio_response = await api_helper.get_portfolio()
        portfolio_json = await portfolio_response.json()
        log.info("Portfolio response: %s", portfolio_json)

        # Validate top-level structure - all required fields
        assert "perp_positions" in portfolio_json, "Response must contain 'perp_positions'"
        assert "send_timestamp_ns" in portfolio_json, "Response must contain 'send_timestamp_ns'"
        assert "spot_positions" in portfolio_json, "Response must contain 'spot_positions'"

        # Validate perp_positions structure
        perp_positions = portfolio_json["perp_positions"]
        assert isinstance(perp_positions, dict), f"'perp_positions' must be a dict, got {type(perp_positions)}"

        # Validate each perp position entry
        for symbol, position in perp_positions.items():
            assert isinstance(symbol, str), f"Perp position symbol must be string, got {type(symbol)}"
            assert_is_number(position, f"Perp position value for {symbol}")

        # Validate spot_positions structure
        spot_positions = portfolio_json["spot_positions"]
        assert isinstance(spot_positions, dict), f"'spot_positions' must be a dict, got {type(spot_positions)}"

        # Validate each spot position entry
        for symbol, position in spot_positions.items():
            assert isinstance(symbol, str), f"Spot position symbol must be string, got {type(symbol)}"
            assert_is_number(position, f"Spot position value for {symbol}", NON_NEGATIVE)
