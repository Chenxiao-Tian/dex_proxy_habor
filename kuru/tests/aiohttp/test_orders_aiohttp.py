import asyncio
import logging

import pytest
import pprint
from aiohttp.test_utils import TestClient
from aiohttp import ClientTimeout

from dexes.kuru.handler.schemas import OrderStatus, ErrorCode

log = logging.getLogger(__name__)


class TestOrdersAiohttp:

    @pytest.mark.asyncio
    async def test_create_order_aiohttp(self, client: TestClient, margin_balance_manager):
        orderbook_contract_addr = "0x05e6f736b5dedd60693fa806ce353156a1b73cf3" # CHOG/MON

        price = "0.00000283"
        size = "10000"

        endpoint = "/private/create-order"

        # Order data
        data = {
            "symbol": orderbook_contract_addr,
            "side": "BUY",
            "price": price,
            "quantity": size,
            "order_type": "LIMIT",
            "client_order_id": "123"
        }

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


    @pytest.mark.asyncio
    async def test_get_orders_aiohttp(self, client: TestClient, margin_balance_manager):
        # First create an order
        orderbook_contract_addr = "0x05e6f736b5dedd60693fa806ce353156a1b73cf3"  # CHOG/MON

        price = "0.00000283"
        size = "10000"

        # Create an order first
        create_endpoint = "/private/create-order"

        data = {
            "symbol": orderbook_contract_addr,
            "side": "BUY",
            "price": price,
            "quantity": size,
            "order_type": "LIMIT",
            "client_order_id": "999"
        }

        log.info(f"Creating order via POST {create_endpoint}")
        create_response = await client.post(create_endpoint, json=data, timeout=ClientTimeout(total=30))
        assert create_response.status == 200

        # Now get all active orders
        list_endpoint = "/public/orders"

        log.info(f"Getting orders via GET {list_endpoint}")
        orders_response = await client.get(list_endpoint, timeout=ClientTimeout(total=30))
        log.info(f"Response status code: {orders_response.status}")

        assert orders_response.status == 200
        response_json = await orders_response.json()
        pprint.pprint(response_json)

        assert "orders" in response_json
        assert isinstance(response_json["orders"], list)
        assert len(response_json["orders"]) > 0, "No orders returned"

        # Verify that all returned orders have OPEN status
        for order in response_json["orders"]:
            assert order["status"] == OrderStatus.OPEN

        # Find our order - it should be there immediately since it starts as OPEN
        our_order = None
        for order in response_json["orders"]:
            if order["client_order_id"] == data["client_order_id"]:
                our_order = order
                break

        assert our_order is not None
        assert our_order["price"] == price
        assert our_order["quantity"] == size
        assert our_order["symbol"] == orderbook_contract_addr
        assert our_order["status"] == OrderStatus.OPEN

    @pytest.mark.parametrize("client_order_id,should_create_order,expected_status,expected_final_status,expected_error_code", [
        pytest.param("777", True, 200, OrderStatus.CANCELLED_PENDING, None, id="cancel_success"),
        pytest.param("999999", False, 404, None, ErrorCode.ORDER_NOT_FOUND, id="cancel_not_found"),
        pytest.param("-1", False, 400, None, ErrorCode.INVALID_PARAMETER, id="cancel_negative_client_order_id"),
        pytest.param("0", False, 400, None, ErrorCode.INVALID_PARAMETER, id="cancel_zero_client_order_id"),
        pytest.param("abc", False, 400, None, ErrorCode.INVALID_PARAMETER, id="cancel_invalid_client_order_id"),
    ])
    @pytest.mark.asyncio
    async def test_cancel_order_scenarios_aiohttp(self, client: TestClient, margin_balance_manager, client_order_id, should_create_order, expected_status, expected_final_status, expected_error_code):
        """Parametrized test for order cancellation scenarios via HTTP API"""
        # DEX Proxy details
        orderbook_contract_addr = "0x05e6f736b5dedd60693fa806ce353156a1b73cf3"  # CHOG/MON
        price = "0.00000283"
        size = "10000"

        # Conditionally create order first
        if should_create_order:
            create_endpoint = "/private/create-order"

            create_data = {
                "symbol": orderbook_contract_addr,
                "side": "BUY",
                "price": price,
                "quantity": size,
                "order_type": "LIMIT",
                "client_order_id": client_order_id
            }

            log.info(f"Creating order via POST {create_endpoint}")
            create_response = await client.post(create_endpoint, json=create_data, timeout=ClientTimeout(total=30))
            assert create_response.status == 200
            create_json = await create_response.json()
            assert "place_tx_id" in create_json

            order_id_exist = await self._check_order_id_was_assigned(client, client_order_id)
            assert order_id_exist

        # Now cancel the order
        cancel_endpoint = "/private/cancel-order"

        cancel_data = {
            "client_order_id": client_order_id
        }

        log.info(f"Cancelling order via DELETE {cancel_endpoint}")
        cancel_response = await client.delete(cancel_endpoint, json=cancel_data, timeout=ClientTimeout(total=30))
        log.info(f"Cancel response status code: {cancel_response.status}")

        cancel_json = await cancel_response.json()

        assert cancel_response.status == expected_status

        if expected_status == 200:
            assert cancel_json["client_order_id"] == client_order_id
            assert cancel_json["status"] == expected_final_status

        if expected_error_code is not None:
            assert cancel_json["error_code"] == expected_error_code

        log.info("Cancel order test completed successfully for")

    async def _check_order_id_was_assigned(self, client: TestClient, client_order_id):
        order_id_exist = False
        for i in range(10):
            log.info(f"Waiting for order to be added to blockchain... {i + 1}/10")
            await asyncio.sleep(1)
            get_order_endpoint = f"/public/order?client_order_id={client_order_id}"
            get_order_response = await client.get(get_order_endpoint, timeout=10)
            order = await get_order_response.json()
            if order["order_id"] is not None and order["order_id"] != "":
                order_id_exist = True
                break
        return order_id_exist
