import asyncio
import logging
from typing import cast

import pytest
import pprint
import requests
from web3 import Web3

from dexes.kuru.handler.schemas import CreateOrderOut, ErrorCode, OrderStatus
from dexes.kuru.util.margin import get_margin_balance

log = logging.getLogger(__name__)


class TestOrdersE2E:

    @pytest.mark.asyncio
    async def test_create_order_e2e(self, dex_proxy_proc):
        orderbook_contract_addr = "0x05e6f736b5dedd60693fa806ce353156a1b73cf3" # CHOG/MON

        price = "0.00000283"
        size = "10000"

        # DEX Proxy details
        host = "http://localhost"
        port = "1958"
        endpoint = "/private/create-order"
        url = f"{host}:{port}{endpoint}"

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
        log.info(f"Sending POST request to {url} with data: {data}")
        response = requests.post(url=url, json=data, timeout=10) # Added timeout
        log.info(f"Response status code: {response.status_code}")
        response_json = response.json()
        pprint.pprint(response_json)

        # Assertions
        assert response.status_code == 200, f"Expected status code 200, got {response.status_code}. Response: {response.text}"
        assert "place_tx_id" in response_json, "Response JSON should contain 'place_tx_id'"
        assert len(response_json["place_tx_id"]) > 0, "'place_tx_id' should not be empty"

        log.info(f"Order creation successful, place_tx_id: {response_json['place_tx_id']}")

    @pytest.mark.asyncio
    async def test_get_orders_e2e(self, dex_proxy_proc):
        # DEX Proxy details
        host = "http://localhost"
        port = "1958"
        
        # First create an order
        orderbook_contract_addr = "0x05e6f736b5dedd60693fa806ce353156a1b73cf3"  # CHOG/MON

        price = "0.00000283"
        size = "10000"

        # Create an order first
        create_endpoint = "/private/create-order"
        create_url = f"{host}:{port}{create_endpoint}"
        
        data = {
            "symbol": orderbook_contract_addr,
            "side": "BUY",
            "price": price,
            "quantity": size,
            "order_type": "LIMIT",
            "client_order_id": "999"
        }

        log.info(f"Creating order via POST {create_url}")
        create_response = requests.post(url=create_url, json=data, timeout=10)
        assert create_response.status_code == 200
        
        # Now get all active orders
        orders_endpoint = "/public/orders"
        orders_url = f"{host}:{port}{orders_endpoint}"
        
        log.info(f"Getting orders via GET {orders_url}")
        orders_response = requests.get(url=orders_url, timeout=10)
        log.info(f"Response status code: {orders_response.status_code}")
        
        assert orders_response.status_code == 200
        response_json = orders_response.json()
        pprint.pprint(response_json)
        
        assert "orders" in response_json
        assert isinstance(response_json["orders"], list)
        
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
        
        # Wait for order to be assigned an order_id (transaction completion)
        order_id_exist = await self._check_order_id_was_assigned(data["client_order_id"], host, port)
        assert order_id_exist

    @pytest.mark.asyncio
    async def test_get_single_order_e2e(self, dex_proxy_proc):
        # DEX Proxy details
        host = "http://localhost"
        port = "1958"

        # First test non-existent order
        order_endpoint = "/public/order"
        order_url = f"{host}:{port}{order_endpoint}/nonexistent"

        log.info(f"Getting non-existent order via GET {order_url}")
        response = requests.get(url=order_url, timeout=10)
        assert response.status_code == 404

        # Now create an order
        orderbook_contract_addr = "0x05e6f736b5dedd60693fa806ce353156a1b73cf3"  # CHOG/MON

        price = "0.00000283"
        size = "10000"

        # Create an order
        create_endpoint = "/private/create-order"
        create_url = f"{host}:{port}{create_endpoint}"

        data = {
            "symbol": orderbook_contract_addr,
            "side": "BUY",
            "price": price,
            "quantity": size,
            "order_type": "LIMIT",
            "client_order_id": "888"
        }

        log.info(f"Creating order via POST {create_url}")
        create_response = requests.post(url=create_url, json=data, timeout=10)
        assert create_response.status_code == 200
        create_json = create_response.json()

        # Get the specific order
        order_url = f"{host}:{port}{order_endpoint}?client_order_id={data['client_order_id']}"

        log.info(f"Getting order via GET {order_url}")
        order_response = requests.get(url=order_url, timeout=10)
        assert order_response.status_code == 200

        order_json = order_response.json()
        pprint.pprint(order_json)

        assert order_json["client_order_id"] == data["client_order_id"]
        assert order_json["price"] == price
        assert order_json["quantity"] == size
        assert order_json["symbol"] == orderbook_contract_addr
        assert order_json["place_tx_id"] == create_json["place_tx_id"]

    # @pytest.mark.asyncio
    # async def test_cancel_all_orders_empty_e2e(self, dex_proxy_proc):
    #     # DEX Proxy details
    #     host = "http://localhost"
    #     port = "1958"
    #
    #     # Cancel all orders when no orders exist
    #     cancel_all_endpoint = "/private/cancel-all-orders"
    #     cancel_all_url = f"{host}:{port}{cancel_all_endpoint}"
    #
    #     log.info(f"Cancelling all orders (empty) via POST {cancel_all_url}")
    #     cancel_response = requests.delete(url=cancel_all_url, timeout=10)
    #     log.info(f"Cancel all response status code: {cancel_response.status_code}")
    #
    #     cancel_json = cancel_response.json()
    #     pprint.pprint(cancel_json)
    #
    #     assert cancel_response.status_code == 200
    #     assert "cancelled" in cancel_json
    #     assert len(cancel_json["cancelled"]) == 0

    @pytest.mark.parametrize("client_order_id,should_create_order,expected_status,expected_final_status,expected_error_code", [
        pytest.param("777", True, 200, OrderStatus.CANCELLED_PENDING, None, id="cancel_success"),
        pytest.param("999999", False, 404, None, ErrorCode.ORDER_NOT_FOUND, id="cancel_not_found"),
        pytest.param("-1", False, 400, None, ErrorCode.INVALID_PARAMETER, id="cancel_negative_client_order_id"),
        pytest.param("0", False, 400, None, ErrorCode.INVALID_PARAMETER, id="cancel_zero_client_order_id"),
        pytest.param("abc", False, 400, None, ErrorCode.INVALID_PARAMETER, id="cancel_invalid_client_order_id"),
    ])
    @pytest.mark.asyncio
    async def test_cancel_order_scenarios_e2e(self, dex_proxy_proc, client_order_id, should_create_order, expected_status, expected_final_status, expected_error_code):
        """Parametrized test for order cancellation scenarios via HTTP API"""
        # DEX Proxy details
        host = "http://localhost"
        port = "1958"
        
        orderbook_contract_addr = "0x05e6f736b5dedd60693fa806ce353156a1b73cf3"  # CHOG/MON
        price = "0.00000283"
        size = "10000"

        # Conditionally create order first
        if should_create_order:
            create_endpoint = "/private/create-order"
            create_url = f"{host}:{port}{create_endpoint}"
            
            create_data = {
                "symbol": orderbook_contract_addr,
                "side": "BUY",
                "price": price,
                "quantity": size,
                "order_type": "LIMIT",
                "client_order_id": client_order_id
            }

            log.info(f"Creating order via POST {create_url}")
            create_response = requests.post(url=create_url, json=create_data, timeout=10)
            assert create_response.status_code == 200
            create_json = create_response.json()
            assert "place_tx_id" in create_json

            order_id_exist = await self._check_order_id_was_assigned(client_order_id, host, port)
            assert order_id_exist

        # Now cancel the order
        cancel_endpoint = "/private/cancel-order"
        cancel_url = f"{host}:{port}{cancel_endpoint}"
        
        cancel_data = {
            "client_order_id": client_order_id
        }

        log.info(f"Cancelling order via DELETE {cancel_url}")
        cancel_response = requests.delete(url=cancel_url, timeout=10, params=cancel_data)
        log.info(f"Cancel response status code: {cancel_response.status_code}")
        
        cancel_json = cancel_response.json()

        assert cancel_response.status_code == expected_status

        if expected_status == 200:
            assert cancel_json["client_order_id"] == client_order_id
            assert cancel_json["status"] == expected_final_status
            
        if expected_error_code is not None:
            assert cancel_json["error_code"] == expected_error_code
            
        log.info("Cancel order test completed successfully for")

    async def _check_order_id_was_assigned(self, client_order_id, host, port):
        order_id_exist = False
        for i in range(10):
            log.info(f"Waiting for order to be added to blockchain... {i + 1}/10")
            await asyncio.sleep(1)
            get_order_url = f"{host}:{port}/public/order?client_order_id={client_order_id}"
            get_order_response = requests.get(url=get_order_url, timeout=10)
            order = get_order_response.json()
            if order["order_id"] is not None and order["order_id"] != "":
                order_id_exist = True
                break
        return order_id_exist

    @pytest.mark.asyncio
    async def test_cancel_all_orders_e2e(self, dex_proxy_proc):
        # DEX Proxy details
        host = "http://localhost"
        port = "1958"
        
        orderbook_contract_addr = "0x05e6f736b5dedd60693fa806ce353156a1b73cf3"  # CHOG/MON
        price = "0.00000283"
        size = "5000"  # Smaller size for multiple orders

        cleared = await self._clear_all_orders(host, port)
        assert cleared

        # Create multiple orders
        create_endpoint = "/private/create-order"
        create_url = f"{host}:{port}{create_endpoint}"
        
        client_order_ids = []
        for i in range(3):
            create_data = {
                "symbol": orderbook_contract_addr,
                "side": "BUY",
                "price": price,
                "quantity": size,
                "order_type": "LIMIT",
                "client_order_id": f"{i+1}"
            }

            log.info(f"Creating order {i+1} via POST {create_url}")
            create_response = requests.post(url=create_url, json=create_data, timeout=10)
            assert create_response.status_code == 200
            client_order_ids.append(create_data["client_order_id"])

            order_id_exist = await self._check_order_id_was_assigned(create_data["client_order_id"], host, port)
            assert order_id_exist
            

        # Cancel all orders
        cancel_all_endpoint = "/private/cancel-all-orders"
        cancel_all_url = f"{host}:{port}{cancel_all_endpoint}"

        log.info(f"Cancelling all orders via POST {cancel_all_url}")
        cancel_response = requests.delete(url=cancel_all_url, timeout=10)
        log.info(f"Cancel all response status code: {cancel_response.status_code}")

        assert cancel_response.status_code == 200

        cancel_json = cancel_response.json()
        assert "cancelled" in cancel_json
        assert len(cancel_json["cancelled"]) == 3

        # Verify all orders were cancelled
        assert set(cancel_json["cancelled"]) == set(int(client_order_id) for client_order_id in client_order_ids)

    async def _clear_all_orders(self, host, port) -> bool:
        # Cancel all orders to clear the blockchain
        cancel_all_endpoint = "/private/cancel-all-orders"
        cancel_all_url = f"{host}:{port}{cancel_all_endpoint}"
        cancel_response = requests.delete(url=cancel_all_url, timeout=10)
        assert cancel_response.status_code == 200

        cleared = False
        for i in range(10):
            get_orders_url = f"{host}:{port}/public/orders"
            get_orders_response = requests.get(url=get_orders_url, timeout=10)
            orders_response = get_orders_response.json()
            # The orders endpoint now only returns OPEN orders
            # So if the list is empty, there are no OPEN orders left
            if len(orders_response.get("orders", [])) == 0:
                cleared = True
                break
            log.info(f"Waiting for orders to be cleared... {i + 1}/10")
            await asyncio.sleep(1)

        return cleared

    @pytest.mark.asyncio
    async def test_get_nonexistent_order_e2e(self, dex_proxy_proc):
        """Test retrieving a non-existent order via HTTP API"""
        # DEX Proxy details
        host = "http://localhost"
        port = "1958"
        
        # Test non-existent order
        order_endpoint = "/public/order"
        order_url = f"{host}:{port}{order_endpoint}/nonexistent"
        
        log.info(f"Getting non-existent order via GET {order_url}")
        response = requests.get(url=order_url, timeout=10)
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_margin_balance_e2e(self, config_data_module, private_key_hex_module):
        rpc_url = config_data_module.get("dex", {}).get("url", "")
        balance = await get_margin_balance(rpc_url, private_key_hex_module, Web3.to_checksum_address("0x7e9953a11e606187be268c3a6ba5f36635149c81"))
        assert balance is not None

        balance = await get_margin_balance(rpc_url, private_key_hex_module, Web3.to_checksum_address("0x94b72620e65577de5fb2b8a8b93328caf6ca161b"))
        assert balance is not None

