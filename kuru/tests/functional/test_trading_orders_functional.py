import asyncio
import logging

import pytest
import pprint
from aiohttp.test_utils import TestClient
from aiohttp import ClientTimeout

from dexes.kuru.tests.functional.market_data import MarketData

log = logging.getLogger(__name__)


class TestOrdersFunctional:

    @pytest.mark.asyncio
    async def test_trade_ioc_order_functional(self, client: TestClient, config_data_module, private_key_hex_module, margin_balance_manager):
        orderbook_contract_addr = "0x05e6f736b5dedd60693fa806ce353156a1b73cf3"  # test CHOG/MON

        market_data = MarketData()
        data = await market_data.get_ioc_order_data(config_data_module, private_key_hex_module, orderbook_contract_addr)

        await self.make_order(client, data)

        await asyncio.sleep(5)
        log.info("Test completed successfully")

    @pytest.mark.asyncio
    async def test_trade_gtc_order_functional(self, client: TestClient, config_data_module, private_key_hex_module, margin_balance_manager):
        orderbook_contract_addr = "0x05e6f736b5dedd60693fa806ce353156a1b73cf3"  # test CHOG/MON

        market_data = MarketData()
        data = await market_data.get_gtc_order_data(config_data_module, private_key_hex_module, orderbook_contract_addr)

        await self.make_order(client, data)
        await asyncio.sleep(5)

        await self.cancel_ordert(client, data)
        await asyncio.sleep(5)

        log.info("Test completed successfully")

    async def cancel_ordert(self, client, data):
        cancel_endpoint = "/private/cancel-order"
        cancel_data = {
            "client_order_id": data["client_order_id"],
        }
        log.info(f"Cancelling order via DELETE {cancel_endpoint}")
        cancel_response = await client.delete(cancel_endpoint, json=cancel_data, timeout=ClientTimeout(total=30))
        log.info(f"Cancel response status code: {cancel_response.status}")
        cancel_json = await cancel_response.json()
        assert cancel_response.status == 200
        assert cancel_json["client_order_id"] == cancel_data["client_order_id"]

    async def make_order(self, client, data):
        endpoint = "/private/create-order"
        # Make the API call to create the order
        log.info(f"Sending POST request to {endpoint} with data: {data}")
        response = await client.post(endpoint, json=data, timeout=ClientTimeout(total=30))
        log.info(f"Response status code: {response.status}")
        response_json = await response.json()
        pprint.pprint(response_json)
        # Assertions
        assert response.status == 200, f"Expected status code 200, got {response.status}. Response: {response.text}"
        assert "place_tx_id" in response_json, "Response JSON should contain 'place_tx_id'"
        assert len(response_json['place_tx_id']) > 0, "'place_tx_id' should not be empty"
        log.info(f"Order creation successful, place_tx_id: {response_json['place_tx_id']}")
