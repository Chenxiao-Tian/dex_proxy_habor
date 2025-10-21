import logging

import pytest

from dex_proxy_api_test_helper import DexProxyApiTestHelper
from common import assert_is_numeric_string, assert_is_valid_solana_address, assert_is_int, POSITIVE, NON_NEGATIVE

log = logging.getLogger(__name__)


class TestTransfers:

    @pytest.mark.asyncio
    async def test_get_transfers(self, api_helper: DexProxyApiTestHelper):
        """Test /public/transfers endpoint."""
        transfers_response = await api_helper.get_transfers()
        transfers_json = await transfers_response.json()
        log.info("Transfers response: %s", transfers_json)

        # Validate HTTP status code
        assert transfers_response.status == 200, f"Expected status code 200, got {transfers_response.status}"

        # Validate top-level structure
        assert "success" in transfers_json, "Response must contain 'success'"
        assert "meta" in transfers_json, "Response must contain 'meta'"
        assert "records" in transfers_json, "Response must contain 'records'"

        # Validate success field
        success = transfers_json["success"]
        assert isinstance(success, bool), f"'success' must be bool, got {type(success)}"
        assert success is True, "'success' should be True"

        # Validate meta structure
        meta = transfers_json["meta"]
        assert isinstance(meta, dict), f"'meta' must be a dict, got {type(meta)}"
        assert "nextPage" in meta, "'meta' must contain 'nextPage'"

        # nextPage can be None or string
        next_page = meta["nextPage"]
        assert next_page is None or isinstance(next_page, str), (
            f"'nextPage' must be None or string, got {type(next_page)}"
        )

        # Validate records structure
        records = transfers_json["records"]
        assert isinstance(records, list), f"'records' must be a list, got {type(records)}"

        # Validate each transfer record
        for record in records:
            assert isinstance(record, dict), f"Each record must be a dict, got {type(record)}"

            # Required fields in each record
            required_fields = [
                'amount', 'depositRecordId', 'direction', 'explanation', 'marketCumulativeBorrowInterest',
                'marketCumulativeDepositInterest', 'marketDepositBalance', 'marketIndex', 'marketWithdrawBalance',
                'oraclePrice', 'slot', 'symbol', 'totalDepositsAfter', 'totalWithdrawsAfter', 'ts', 'txSig',
                'txSigIndex', 'user', 'userAuthority'
            ]
            for field in required_fields:
                assert field in record, f"Transfer record must contain '{field}'"

            # Validate amount (string with decimals, non-negative)
            assert_is_numeric_string(record['amount'], 'amount', NON_NEGATIVE)

            # Validate depositRecordId
            deposit_id = record['depositRecordId']
            assert isinstance(deposit_id, str), f"'depositRecordId' must be string, got {type(deposit_id)}"

            # Validate direction
            direction = record['direction']
            assert isinstance(direction, str), f"'direction' must be string, got {type(direction)}"
            assert direction in ['deposit', 'withdraw'], f"'direction' must be 'deposit' or 'withdraw', got {direction}"

            # Validate explanation
            explanation = record['explanation']
            assert isinstance(explanation, str), f"'explanation' must be string, got {type(explanation)}"

            # Validate market fields (all numeric strings)
            for market_field in [
                'marketCumulativeBorrowInterest', 'marketCumulativeDepositInterest',
                'marketDepositBalance', 'marketWithdrawBalance'
            ]:
                assert_is_numeric_string(record[market_field], market_field)

            # Validate marketIndex
            assert_is_int(record['marketIndex'], 'marketIndex', NON_NEGATIVE)

            # Validate oraclePrice (positive numeric string)
            assert_is_numeric_string(record['oraclePrice'], 'oraclePrice', POSITIVE)

            # Validate slot
            assert_is_int(record['slot'], 'slot', POSITIVE)

            # Validate symbol
            symbol = record['symbol']
            assert isinstance(symbol, str), f"'symbol' must be string, got {type(symbol)}"
            assert len(symbol) > 0, "'symbol' must not be empty"

            # Validate total amounts (numeric strings, no constraint)
            for total_field in ['totalDepositsAfter', 'totalWithdrawsAfter']:
                assert_is_numeric_string(record[total_field], total_field)

            # Validate ts (timestamp)
            ts = assert_is_int(record['ts'], 'ts', POSITIVE)
            # Timestamp should be in seconds (10 digits)
            assert len(str(ts)) == 10, f"'ts' should be Unix timestamp in seconds, got {ts}"

            # Validate txSig (transaction signature)
            tx_sig = record['txSig']
            assert isinstance(tx_sig, str), f"'txSig' must be string, got {type(tx_sig)}"
            assert len(tx_sig) > 32, f"'txSig' should be valid transaction signature, got {tx_sig}"

            # Validate txSigIndex
            assert_is_int(record['txSigIndex'], 'txSigIndex', NON_NEGATIVE)

            # Validate user (Solana address)
            assert_is_valid_solana_address(record['user'], 'user')

            # Validate userAuthority (Solana address)\
            assert_is_valid_solana_address(record['userAuthority'], 'userAuthority')
