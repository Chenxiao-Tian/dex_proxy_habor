import logging

import pytest

from dex_proxy_api_test_helper import DexProxyApiTestHelper
from common import assert_is_number, NON_NEGATIVE

log = logging.getLogger(__name__)


class TestBalance:

    @pytest.mark.asyncio
    async def test_get_balance(self, api_helper: DexProxyApiTestHelper):
        balance_response = await api_helper.get_balance()
        balance_json = await balance_response.json()
        log.info("Balance response: %s", balance_json)

        # Check top-level structure
        assert "success" in balance_json
        assert balance_json["success"] is True
        assert "balances" in balance_json
        assert isinstance(balance_json["balances"], list)
        assert len(balance_json["balances"]) > 0

        # Check each balance entry
        for balance in balance_json["balances"]:
            assert "symbol" in balance
            assert "mint" in balance
            assert "decimals" in balance
            assert "status" in balance
            assert "balance" in balance
            assert_is_number(balance["balance"], "balance", NON_NEGATIVE)
            assert balance["status"] in ["active", "reduceonly"]
