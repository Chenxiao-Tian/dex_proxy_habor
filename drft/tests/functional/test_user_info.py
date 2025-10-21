import logging

import pytest

from dex_proxy_api_test_helper import DexProxyApiTestHelper
from common import assert_is_valid_solana_address, assert_is_int, NON_NEGATIVE

log = logging.getLogger(__name__)


class TestUserInfo:

    @pytest.mark.asyncio
    async def test_get_user_info(self, api_helper: DexProxyApiTestHelper):
        """Test /public/user-info endpoint."""
        user_info_response = await api_helper.get_user_info()
        user_info_json = await user_info_response.json()
        log.info("User info response: %s", user_info_json)

        # Validate required fields presence
        assert "associated_token_accounts" in user_info_json, "Response must contain 'associated_token_accounts'"
        assert "subaccount_id" in user_info_json, "Response must contain 'subaccount_id'"
        assert "user_public_key" in user_info_json, "Response must contain 'user_public_key'"
        assert "wallet_public_key" in user_info_json, "Response must contain 'wallet_public_key'"

        # Validate associated_token_accounts structure
        ata_list = user_info_json["associated_token_accounts"]
        assert isinstance(ata_list, list), f"'associated_token_accounts' must be a list, got {type(ata_list)}"

        # Validate each associated token account
        for ata_entry in ata_list:
            assert isinstance(ata_entry, dict), f"Each ATA entry must be a dict, got {type(ata_entry)}"

            # Required fields in each ATA entry
            assert "ata" in ata_entry, "ATA entry must contain 'ata'"
            assert "market_index" in ata_entry, "ATA entry must contain 'market_index'"
            assert "symbol" in ata_entry, "ATA entry must contain 'symbol'"

            # Validate ata (Solana address)
            assert_is_valid_solana_address(ata_entry["ata"], "ata")

            # Validate market_index
            assert_is_int(ata_entry["market_index"], 'market_index', NON_NEGATIVE)

            # Validate symbol
            symbol = ata_entry["symbol"]
            assert isinstance(symbol, str), f"'symbol' must be string, got {type(symbol)}"
            assert len(symbol) > 0, "'symbol' must not be empty"

        # Validate subaccount_id
        assert_is_int(user_info_json["subaccount_id"], 'subaccount_id', NON_NEGATIVE)

        # Validate user_public_key (Solana address)
        assert_is_valid_solana_address(user_info_json["user_public_key"], "user_public_key")

        # Validate wallet_public_key (Solana address)
        assert_is_valid_solana_address(user_info_json["wallet_public_key"], "wallet_public_key")
