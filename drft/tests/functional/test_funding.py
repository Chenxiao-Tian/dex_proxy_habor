import logging

import pytest

from dex_proxy_api_test_helper import DexProxyApiTestHelper
from common import assert_is_numeric_string, assert_is_int, POSITIVE, NON_NEGATIVE
from drft.tests.functional.common import assert_is_valid_solana_address

log = logging.getLogger(__name__)


class TestFunding:

    @pytest.mark.asyncio
    async def test_get_funding(self, api_helper: DexProxyApiTestHelper):
        """Test /public/funding endpoint."""
        funding_response = await api_helper.get_funding()
        funding_json = await funding_response.json()
        log.info("Funding response: %s", funding_json)

        # Validate HTTP status code
        assert funding_response.status == 200, f"Expected status code 200, got {funding_response.status}"

        # Validate top-level structure
        assert "success" in funding_json, "Response must contain 'success'"
        assert "meta" in funding_json, "Response must contain 'meta'"
        assert "records" in funding_json, "Response must contain 'records'"

        # Validate success field
        success = funding_json["success"]
        assert isinstance(success, bool), f"'success' must be bool, got {type(success)}"
        assert success is True, "'success' should be True"

        # Validate meta structure
        meta = funding_json["meta"]
        assert isinstance(meta, dict), f"'meta' must be a dict, got {type(meta)}"
        assert "nextPage" in meta, "'meta' must contain 'nextPage'"

        # nextPage can be None or string
        next_page = meta["nextPage"]
        assert next_page is None or isinstance(next_page, str), (
            f"'nextPage' must be None or string, got {type(next_page)}"
        )

        # Validate records structure
        records = funding_json["records"]
        assert isinstance(records, list), f"'records' must be a list, got {type(records)}"

        # Validate each funding record
        for record in records:
            assert isinstance(record, dict), f"Each record must be a dict, got {type(record)}"

            # Required fields in each record
            required_fields = [
                'ammCumulativeFundingLong', 'ammCumulativeFundingShort', 'baseAssetAmount', 'fundingPayment',
                'marketIndex', 'nativeCode', 'slot', 'ts', 'txSig', 'txSigIndex', 'user', 'userAuthority',
                'userLastCumulativeFunding'
            ]
            for field in required_fields:
                assert field in record, f"Funding record must contain '{field}'"

            # Validate ammCumulativeFundingLong (string with decimals)
            assert_is_numeric_string(record['ammCumulativeFundingLong'], 'ammCumulativeFundingLong')

            # Validate ammCumulativeFundingShort (string with decimals)
            assert_is_numeric_string(record['ammCumulativeFundingShort'], 'ammCumulativeFundingShort')

            # Validate baseAssetAmount (string with decimals)
            assert_is_numeric_string(record['baseAssetAmount'], 'baseAssetAmount')

            # Validate fundingPayment (string with decimals)
            assert_is_numeric_string(record['fundingPayment'], 'fundingPayment')

            # Validate marketIndex
            assert_is_int(record['marketIndex'], 'marketIndex', NON_NEGATIVE)

            # Validate nativeCode (market symbol)
            native_code = record['nativeCode']
            assert isinstance(native_code, str), f"'nativeCode' must be string, got {type(native_code)}"
            assert len(native_code) > 0, "'nativeCode' must not be empty"

            # Validate slot
            assert_is_int(record['slot'], 'slot', POSITIVE)

            # Validate ts (timestamp)
            assert_is_int(record['ts'], 'ts', POSITIVE)

            # Validate txSig (transaction signature)
            tx_sig = record['txSig']
            assert isinstance(tx_sig, str), f"'txSig' must be string, got {type(tx_sig)}"

            # Validate txSigIndex
            assert_is_int(record['txSigIndex'], 'txSigIndex', NON_NEGATIVE)

            # Validate user (Solana address)
            assert_is_valid_solana_address(record['user'], 'user')

            # Validate userAuthority (Solana address)
            assert_is_valid_solana_address(record['userAuthority'], 'userAuthority')

            # Validate userLastCumulativeFunding
            assert_is_numeric_string(record['userLastCumulativeFunding'], 'userLastCumulativeFunding')