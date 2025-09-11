import asyncio
import logging
from typing import Optional

import pytest
import pytest_asyncio

from dexes.kuru.handler.handler import KuruHandlerSingleton
from dexes.kuru.handler.schemas import OrderStatus
from dexes.kuru.util.margin import add_margin_balance
from dexes.kuru.tests.common import read_config
from schemas import QueryLiveOrdersResponse

log = logging.getLogger(__name__)

class TestOrdersIT:
    @pytest_asyncio.fixture(autouse=True)
    async def reset_handler(self):
        log.info("Resetting handler before test")
        await KuruHandlerSingleton.reset_instance()
        log.info("Handler reset before test")

        yield
        log.info("Resetting handler after test")
        await KuruHandlerSingleton.reset_instance()
        log.info("Handler reset after test")
#
    @pytest.mark.asyncio
    async def test_create_order_it(self):
        config_data, private_key_hex = read_config()

        orderbook_contract_addr = "0x05e6f736b5dedd60693fa806ce353156a1b73cf3" # CHOG/MON

        price = "0.00000283"
        size = "10000"
        num_orders = 1

        await add_margin_balance(config_data['dex']['url'], price, size, num_orders, private_key_hex)

        data = {
            "symbol": orderbook_contract_addr,
            "side": "BUY",
            "price": price,
            "quantity": size,
            "order_type": "LIMIT",
            "client_order_id": "123"
        }

        handler = KuruHandlerSingleton.get_instance({"url": config_data['dex']['url']})
        await handler.start(private_key_hex)

        status, response = await handler.create_order("", data, 12345)

        assert status == 200
        assert response.client_order_id == data["client_order_id"]
        assert len(response.place_tx_id) > 0

        # Wait for the transaction to complete with 10 second timeout
        log.info(f"Waiting for order completion for client_order_id: {data['client_order_id']}")
        tx_status = await self.wait_for_order_completion(handler, data["client_order_id"], timeout=10.0)

        assert tx_status is not None, "Transaction completion timed out after 10 seconds"
        assert tx_status == 1, f"Transaction failed with status: {tx_status}"

        log.info(f"Order completed successfully with transaction status: {tx_status}")

        log.info("Stopping nonce manager")
        await handler.nonce_manager.stop()
        log.info("Nonce manager stopped")

    @pytest.mark.asyncio
    async def test_get_orders_it(self):
        config_data, private_key_hex = read_config()

        # Create a new order
        orderbook_contract_addr = "0x05e6f736b5dedd60693fa806ce353156a1b73cf3"  # CHOG/MON
        price = "0.00000283"
        size = "10000"
        num_orders = 1

        await add_margin_balance(config_data['dex']['url'], price, size, num_orders, private_key_hex)

        handler = KuruHandlerSingleton.get_instance({"url": config_data['dex']['url']})
        await handler.start(private_key_hex)

        # Get initial orders (should only include OPEN orders)
        status, response = await handler.orders("", {}, 12345)
        assert status == 200
        assert isinstance(response, QueryLiveOrdersResponse)
        # Verify that all returned orders have OPEN status
        for order in response.orders:
            assert order.status == OrderStatus.OPEN
        initial_order_count = len(response.orders)

        data = {
            "symbol": orderbook_contract_addr,
            "side": "BUY",
            "price": price,
            "quantity": size,
            "order_type": "LIMIT",
            "client_order_id": "456"
        }

        # Create order
        status, _ = await handler.create_order("", data, 12345)
        assert status == 200

        # Get orders immediately after creation - should now include the new order
        # because it starts with OPEN status immediately
        status, response = await handler.orders("", {}, 12345)
        assert status == 200
        assert len(response.orders) == initial_order_count + 1  # Should include new order
        # Verify that all returned orders have OPEN status
        for order in response.orders:
            assert order.status == OrderStatus.OPEN

        # Find our order in the list
        our_order = None
        for order in response.orders:
            if order.client_order_id == data["client_order_id"]:
                our_order = order
                break

        assert our_order is not None
        assert our_order.price == price
        assert our_order.quantity == size
        assert our_order.symbol == orderbook_contract_addr
        assert our_order.side == "BUY"
        assert our_order.status == OrderStatus.OPEN

        # Wait for transaction to complete to ensure order_id is assigned
        tx_status = await self.wait_for_order_completion(handler, data["client_order_id"], timeout=10.0)
        assert tx_status is not None, "Transaction completion timed out after 10 seconds"
        assert tx_status == 1, f"Transaction failed with status: {tx_status}"

        log.info("Stopping nonce manager")
        await handler.nonce_manager.stop()
        log.info("Nonce manager stopped")

    @pytest.mark.asyncio
    async def test_get_single_order_it(self):
        config_data, private_key_hex = read_config()

        # Create a new order
        orderbook_contract_addr = "0x05e6f736b5dedd60693fa806ce353156a1b73cf3"  # CHOG/MON
        price = "0.00000283"
        size = "10000"
        num_orders = 1

        await add_margin_balance(config_data['dex']['url'], price, size, num_orders, private_key_hex)


        handler = KuruHandlerSingleton.get_instance({"url": config_data['dex']['url']})
        await handler.start(private_key_hex)

        # Try to get a non-existent order
        params = {"client_order_id": "9999"}
        status, response = await handler.order("", params, 12345)
        assert status == 404
        assert "error_code" in response


        data = {
            "symbol": orderbook_contract_addr,
            "side": "BUY",
            "price": price,
            "quantity": size,
            "order_type": "LIMIT",
            "client_order_id": "789"
        }

        # Create order
        status, create_response = await handler.create_order("", data, 12345)
        assert status == 200

        # Get the specific order
        params = {"client_order_id": data["client_order_id"]}
        status, order_response = await handler.order("", params, 12345)
        assert status == 200
        assert order_response.client_order_id == data["client_order_id"]
        assert order_response.price == price
        assert order_response.quantity == size
        assert order_response.symbol == orderbook_contract_addr
        assert order_response.side == "BUY"
        assert order_response.place_tx_id == create_response.place_tx_id

        tx_status = await self.wait_for_order_completion(handler, data["client_order_id"], timeout=10.0)
        assert tx_status is not None, "Transaction completion timed out after 10 seconds"
        assert tx_status == 1, f"Transaction failed with status: {tx_status}"
        
        log.info("Stopping nonce manager")
        await handler.nonce_manager.stop()
        log.info("Nonce manager stopped")


    async def wait_for_order_completion(self, handler, client_order_id: str, timeout: float = 10.0) -> Optional[int]:
        order_completions = handler.get_order_completions()
        if client_order_id not in order_completions:
            return None

        completion = order_completions[client_order_id]

        try:
            await asyncio.wait_for(completion.event.wait(), timeout=timeout)
            status = completion.result_status
            handler.cleanup_order_completion(client_order_id)

            return status
        except asyncio.TimeoutError:
            handler.cleanup_order_completion(client_order_id)
            return None

    @pytest.mark.asyncio
    async def test_cancel_order_it(self):
        config_data, private_key_hex = read_config()

        orderbook_contract_addr = "0x05e6f736b5dedd60693fa806ce353156a1b73cf3"  # CHOG/MON

        price = "0.00000283"
        size = "10000"
        num_orders = 1

        await add_margin_balance(config_data['dex']['url'], price, size, num_orders, private_key_hex)

        handler = KuruHandlerSingleton.get_instance({"url": config_data['dex']['url']})
        await handler.start(private_key_hex)

        # Create an order first
        create_data = {
            "symbol": orderbook_contract_addr,
            "side": "BUY",
            "price": price,
            "quantity": size,
            "order_type": "LIMIT",
            "client_order_id": "789"
        }

        status, response = await handler.create_order("", create_data, 12345)
        assert status == 200
        assert response.client_order_id == create_data["client_order_id"]

        # Wait for the order creation to complete
        tx_status = await self.wait_for_order_completion(handler, create_data["client_order_id"], timeout=10.0)
        assert tx_status is not None, "Order creation timed out"
        assert tx_status == 1, f"Order creation failed with status: {tx_status}"
        
        # Verify order is in cache and OPEN
        assert create_data["client_order_id"] in handler._orders_cache
        assert handler._orders_cache[create_data["client_order_id"]].status == OrderStatus.OPEN

        # Now cancel the order
        cancel_data = {"client_order_id": create_data["client_order_id"]}
        status, cancel_response = await handler.cancel_order("", cancel_data, 12345)

        assert status == 200
        assert cancel_response.client_order_id == create_data["client_order_id"]
        assert cancel_response.status == OrderStatus.CANCELLED_PENDING


        assert handler._orders_cache[create_data["client_order_id"]].status == OrderStatus.CANCELLED_PENDING


    @pytest.mark.asyncio
    async def test_cancel_all_orders_it(self):
        config_data, private_key_hex = read_config()

        orderbook_contract_addr = "0x05e6f736b5dedd60693fa806ce353156a1b73cf3"  # CHOG/MON

        price = "0.00000283"
        size = "5000"  # Smaller size for multiple orders
        num_orders = 3

        await add_margin_balance(config_data['dex']['url'], price, size, num_orders, private_key_hex)

        handler = KuruHandlerSingleton.get_instance({"url": config_data['dex']['url']})
        await handler.start(private_key_hex)

        # Create multiple orders
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

            status, _ = await handler.create_order("", create_data, 12345)
            assert status == 200
            client_order_ids.append(create_data["client_order_id"])

        # Wait for all orders to complete
        for client_order_id in client_order_ids:
            tx_status = await self.wait_for_order_completion(handler, client_order_id, timeout=10.0)
            assert tx_status is not None, f"Order creation timed out for {client_order_id}"
            assert tx_status == 1, f"Order creation failed for {client_order_id}"

        # Verify all orders are still OPEN
        for client_order_id in client_order_ids:
            assert client_order_id in handler._orders_cache
            assert handler._orders_cache[client_order_id].status == "OPEN"

        # Cancel all orders
        status, cancel_response = await handler.cancel_all_orders("", {}, 12345)

        assert status == 200
        assert len(cancel_response.cancelled) == 3
        assert set(cancel_response.cancelled) == set(int(client_order_id) for client_order_id in client_order_ids)


    @pytest.mark.asyncio
    async def test_cancel_order_not_found_it(self):
        config_data, private_key_hex = read_config()

        handler = KuruHandlerSingleton.get_instance({"url": config_data['dex']['url']})
        await handler.start(private_key_hex)

        # Try to cancel a non-existent order
        cancel_data = {"client_order_id": "999999"}
        status, response = await handler.cancel_order("", cancel_data, 12345)

        assert status == 404
        assert response.error_code == "ORDER_NOT_FOUND"
        assert "not found" in response.error_message

        log.info("Stopping nonce manager")
        await handler.nonce_manager.stop()
        log.info("Nonce manager stopped")
