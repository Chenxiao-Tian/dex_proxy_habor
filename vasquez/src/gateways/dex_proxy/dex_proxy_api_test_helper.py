import logging
from typing import Optional
import time
import functools
from collections import defaultdict

import asyncio
from aiohttp import ClientTimeout
from aiohttp.test_utils import TestClient

log = logging.getLogger(__name__)


REQUEST_STATS = defaultdict(lambda: {'count': 0, 'total_time': 0.0})

def print_stats():
    if not REQUEST_STATS:
        return
    log.info("Execution time statistics:")
    for method, data in sorted(REQUEST_STATS.items()):
        avg_time = data['total_time'] / data['count'] if data['count'] > 0 else 0
        log.info(f"  {method}: called {data['count']} times, total time {data['total_time']:.4f}s, avg time {avg_time:.4f}s")


class DexProxyApiTestHelper:
    def __init__(self, client: TestClient):
        self.client = client

    def update_stats(self, method_name, start_time):
        duration = time.monotonic() - start_time
        REQUEST_STATS[method_name]['count'] += 1
        REQUEST_STATS[method_name]['total_time'] += duration

    def ws_connect(self):
        start_time = time.monotonic()
        endpoint = "/private/ws"
        ws_connect_obj = self.client.ws_connect(endpoint)
        self.update_stats('client.ws_connect' + ' - ' + endpoint, start_time)
        return ws_connect_obj

    async def ws_subscribe(self, ws):
        sub = {
            'id': 1,
            'jsonrpc': '2.0',
            'method': 'subscribe',
            'params': {'channel': 'ORDER'}
        }
        log.info(f"Subscription request: {sub}")
        await ws.send_json(sub)
        sub_reply = await ws.receive_json()
        log.info(f"Subscription reply: {sub_reply}")
        sub = {
            'id': 2,
            'jsonrpc': '2.0',
            'method': 'subscribe',
            'params': {'channel': 'TRADE'}
        }
        log.info(f"Subscription request: {sub}")
        await ws.send_json(sub)
        sub_reply = await ws.receive_json()
        log.info(f"Subscription reply: {sub_reply}")

    async def cancel_order(self, data, expected_status: Optional[int] = 200):
        cancel_endpoint = "/private/cancel-order"
        cancel_data = {
            "client_order_id": data["client_order_id"],
        }
        log.info(f"Cancelling order via DELETE {cancel_endpoint}")
        start_time = time.monotonic()
        cancel_response = await self.client.delete(cancel_endpoint, timeout=ClientTimeout(total=30), params=cancel_data)
        self.update_stats('client.delete' + ' - ' + cancel_endpoint, start_time)
        log.info(f"Cancel response status code: {cancel_response.status}")
        cancel_json = await cancel_response.json()
        assert cancel_response.status == expected_status

        if expected_status == 200:
            assert cancel_json["client_order_id"] == int(cancel_data["client_order_id"])

        return cancel_response

    async def make_order(self, data):
        endpoint = "/private/create-order"
        # Make the API call to create the order
        log.info(f"Sending POST request to {endpoint} with data: {data}")
        start_time = time.monotonic()
        response = await self.client.post(endpoint, json=data, timeout=ClientTimeout(total=30))
        self.update_stats('client.post' + ' - ' + endpoint, start_time)
        log.info(f"Response status code: {response.status}")
        response_json = await response.json()
        log.info(f"Create order response JSON body: {response_json}")
        # Assertions
        assert response.status == 200, f"Expected status code 200, got {response.status}. Response: {await response.text()}"
        assert "place_tx_sig" in response_json, "Response JSON should contain 'place_tx_sig'"
        assert len(response_json['place_tx_sig']) > 0, "'place_tx_sig' should not be empty"
        log.info(f"Order creation successful, place_tx_sig: {response_json['place_tx_sig']}")

        return response

    async def check_order_id_was_assigned(self, client_order_id):
        order_id_exist = False
        num_tries = 60
        for i in range(num_tries):
            log.info(f"Waiting for order to be added to blockchain... {i + 1}/{num_tries}")
            await asyncio.sleep(1)
            get_order_response = await self.get_order(client_order_id)
            order = await get_order_response.json()
            if order["order_id"] is not None and order["order_id"] != "":
                order_id_exist = True
                break
        return order_id_exist

    async def get_order(self, client_order_id, expected_status: Optional[int] = 200):
        endpoint = "/public/order"
        get_order_url = f"{endpoint}?client_order_id={client_order_id}"
        start_time = time.monotonic()
        get_order_response = await self.client.get(get_order_url, timeout=ClientTimeout(total=10))
        self.update_stats('client.get' + ' - ' + endpoint, start_time)

        assert get_order_response.status == expected_status
        return get_order_response
    
    async def get_balance(self):
        endpoint = "/public/balance"
        start_time = time.monotonic()
        get_balance_response = await self.client.get(endpoint, timeout=ClientTimeout(total=10))
        self.update_stats('client.get' + ' - ' + endpoint, start_time)
        assert get_balance_response.status == 200
        return get_balance_response

    async def cancel_all_orders(self, pre_check_orders: Optional[bool] = True):
        if pre_check_orders and not await self.check_orders():
            return None

        cancel_all_endpoint = "/private/cancel-all-orders"
        start_time = time.monotonic()
        cancel_response = await self.client.delete(cancel_all_endpoint, timeout=ClientTimeout(total=120))
        self.update_stats('client.delete' + ' - ' + cancel_all_endpoint, start_time)
        assert cancel_response.status == 200

        num_tries = 60
        for i in range(num_tries):
            if await self.check_orders():
                log.info(f"Waiting for orders should be cleared ... {i + 1}/{num_tries}")
                await asyncio.sleep(1)
            else:
                break

        return cancel_response

    async def check_orders(self) -> bool:
        orders_exist = False
        orders_response = await self.get_orders()
        orders_json = await orders_response.json()
        if orders_json["orders"] is not None and len(orders_json["orders"]) > 0:
            orders_exist = True
        return orders_exist

    async def get_orders(self, expected_status: Optional[int] = 200):
        orders_endpoint = "/public/orders"
        log.info(f"Getting orders via GET {orders_endpoint}")
        start_time = time.monotonic()
        orders_response = await self.client.get(orders_endpoint, timeout=ClientTimeout(total=10))
        self.update_stats('client.get' + ' - ' + orders_endpoint, start_time)
        log.info(f"Response status code: {orders_response.status}")
        assert orders_response.status == expected_status
        return orders_response
