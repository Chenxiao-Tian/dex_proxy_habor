import logging
import random
from typing import Optional, Callable, Any, List
import time
from collections import defaultdict

import asyncio
from aiohttp import ClientTimeout, ClientResponse
from aiohttp.test_utils import TestClient

from retry_executor import RetryExecutor

log = logging.getLogger(__name__)


REQUEST_STATS = defaultdict(lambda: {
    'count': 0,
    'total_time': 0.0,
    'retry_count': 0,
    'timeout_count': 0,
    'error_count': 0
})

FAILED_CLIENT_ORDER_IDS = set()


def print_stats():
    if not REQUEST_STATS:
        return
    log.info("Execution time statistics:")
    for method, data in sorted(REQUEST_STATS.items()):
        avg_time = data['total_time'] / data['count'] if data['count'] > 0 else 0
        log.info(
            f"  {method}: called {data['count']} times, "
            f"total time {data['total_time']:.4f}s, "
            f"avg time {avg_time:.4f}s, "
            f"retries {data['retry_count']}, "
            f"timeouts {data['timeout_count']}, "
            f"errors {data['error_count']}"
        )


class DexProxyApiTestHelper:
    def __init__(self, client: TestClient):
        self.client = client

        self.create_max_timeout = 120
        self.create_request_timeout = 15

        self.cancel_max_timeout = 120
        self.cancel_request_timeout = 15

        self.cancel_all_max_timeout = 120
        self.cancel_all_request_timeout = 15

        self.get_timeout = 10

        self.get_all_timeout = 10

        self.retry_delay = 1.0  # seconds between retries

        self.get_all_num_tries_after_cancel_all_orders = 60

        self.retry_executor = RetryExecutor(
            stats_updater=self.update_stats,
            retry_delay=self.retry_delay
        )

    def update_stats(
        self,
        method_name,
        start_time,
        retry_count=0,
        had_timeout=False,
        had_error=False
    ):
        duration = time.monotonic() - start_time
        REQUEST_STATS[method_name]['count'] += 1
        REQUEST_STATS[method_name]['total_time'] += duration
        REQUEST_STATS[method_name]['retry_count'] += retry_count
        if had_timeout:
            REQUEST_STATS[method_name]['timeout_count'] += 1
        if had_error:
            REQUEST_STATS[method_name]['error_count'] += 1

    async def _execute_with_retry(
        self,
        request_func: Callable,
        max_timeout: float,
        request_timeout: float,
        operation_name: str,
        retry_delay: float = None,
        retry_on_statuses: Optional[List[int]] = None,
        on_retry_callback: Optional[Callable[[Exception, int, str], Any]] = None
    ) -> ClientResponse:
        return await self.retry_executor.execute(
            request_func, max_timeout, request_timeout, operation_name,
            retry_delay, retry_on_statuses, on_retry_callback
        )

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

    async def cancel_order(
        self,
        data,
        expected_status: Optional[int] = 200,
        request_timeout: Optional[float] = None,
        max_timeout: Optional[float] = None,
    ):

        cancel_endpoint = "/private/cancel-order"
        cancel_data = {
            "account": data["account"],
            "client_order_id": data["client_order_id"],
        }
        log.info(f"Cancelling order via DELETE {cancel_endpoint}")

        async def request_func(timeout):
            return await self.client.delete(cancel_endpoint, timeout=timeout, params=cancel_data)

        cancel_response = await self._execute_with_retry(
            request_func=request_func,
            max_timeout=max_timeout if max_timeout else self.cancel_max_timeout,
            request_timeout=request_timeout if request_timeout else self.cancel_request_timeout,
            operation_name=f'client.delete - {cancel_endpoint}'
        )

        log.info(f"Cancel response status code: {cancel_response.status}")

        if expected_status:
            cancel_json = await cancel_response.json()
            assert cancel_response.status == expected_status, \
                (f"Expected status code {expected_status}, got {cancel_response.status}. "
                 f"Response: {await cancel_response.text()}")

            if expected_status == 200:
                assert cancel_json["client_order_id"] == int(cancel_data["client_order_id"])

        return cancel_response

    async def make_order(self, data, expected_status: Optional[int] = 200,
                         retry_on_statuses: Optional[List[int]] = None) -> tuple[ClientResponse, Any]:
        """
        Create an order via POST /private/create-order

        It returns data because client_order_id can be changed during a retry
        :param expected_status:
        :param retry_on_statuses:
        :param data:
        :return: tuple of (ClientResponse, data)
        """

        if retry_on_statuses is None:
            retry_on_statuses = [400, 500]

        endpoint = "/private/create-order"
        log.info(f"Sending POST request to {endpoint} with data: {data}")

        async def request_func(timeout):
            data['client_order_id'] = str(int(random.random() * 100000))
            return await self.client.post(
                endpoint, json=data, timeout=timeout
            )

        async def on_retry_callback(error: Exception, attempt: int, operation_name: str):
            await asyncio.sleep(0)
            log.warning(
                f"Callback after failure of {data['client_order_id']} order creation retrying {operation_name} "
                f"due to error: {str(error)} on attempt {attempt}."
            )
            FAILED_CLIENT_ORDER_IDS.add(data['client_order_id'])

        response = await self._execute_with_retry(
            request_func=request_func,
            max_timeout=self.create_max_timeout,
            request_timeout=self.create_request_timeout,
            operation_name=f'client.post - {endpoint}',
            retry_on_statuses=retry_on_statuses,
            on_retry_callback=on_retry_callback
        )

        log.info(f"Response status code: {response.status}")
        response_json = await response.json()
        log.info(f"Create order response JSON body: {response_json}")
        # Assertions
        assert response.status == expected_status, (
            f"Expected status code {expected_status}, got {response.status}. Response: {await response.text()}"
        )

        if expected_status == 200:
            assert "place_tx_sig" in response_json, "Response JSON should contain 'place_tx_sig'"
            assert len(response_json['place_tx_sig']) > 0, "'place_tx_sig' should not be empty"
            log.info(f"Order creation successful, place_tx_sig: {response_json['place_tx_sig']}")

        return response, data

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
        get_order_response = await self.client.get(
            get_order_url, timeout=ClientTimeout(total=self.get_timeout)
        )
        self.update_stats('client.get' + ' - ' + endpoint, start_time)

        if expected_status:
            assert get_order_response.status == expected_status, (
                f"Expected status code {expected_status}, got {get_order_response.status}. "
                f"Response: {await get_order_response.text()}"
            )

        return get_order_response

    async def cancel_all_orders(
            self, pre_check_orders: Optional[bool] = True, wait_for_clear: Optional[bool] = True
    ) -> Optional[ClientResponse]:
        if pre_check_orders and not await self.check_orders():
            return None

        cancel_all_endpoint = "/private/cancel-all-orders"

        async def request_func(timeout):
            return await self.client.delete(
                cancel_all_endpoint, timeout=timeout
            )

        cancel_response = await self._execute_with_retry(
            request_func=request_func,
            max_timeout=self.cancel_all_max_timeout,
            request_timeout=self.cancel_all_request_timeout,
            operation_name=f'client.delete - {cancel_all_endpoint}'
        )

        assert cancel_response.status == 200

        if wait_for_clear:
            num_tries = self.get_all_num_tries_after_cancel_all_orders
            for i in range(num_tries):
                if await self.check_orders_except_failures():
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

    async def check_orders_except_failures(self) -> bool:
        orders_exist = False
        orders_response = await self.get_orders()
        orders_json = await orders_response.json()
        if orders_json["orders"] is not None and len(orders_json["orders"]) > 0:
            for order in orders_json["orders"]:
                if order["client_order_id"] not in FAILED_CLIENT_ORDER_IDS:
                    orders_exist = True
                    break
        return orders_exist

    async def get_orders(self, expected_status: Optional[int] = 200):
        orders_endpoint = "/public/orders"
        log.info(f"Getting orders via GET {orders_endpoint}")
        start_time = time.monotonic()
        orders_response = await self.client.get(
            orders_endpoint, timeout=ClientTimeout(total=self.get_all_timeout)
        )
        self.update_stats('client.get' + ' - ' + orders_endpoint, start_time)
        log.info(f"Response status code: {orders_response.status}")
        assert orders_response.status == expected_status
        return orders_response

    async def get_balance(self, expected_status: Optional[int] = 200):
        endpoint = "/public/balance"
        log.info(f"Getting balance via GET {endpoint}")
        start_time = time.monotonic()
        balance_response = await self.client.get(endpoint, timeout=ClientTimeout(total=30))
        self.update_stats('client.get' + ' - ' + endpoint, start_time)
        log.info(f"Response status code: {balance_response.status}")
        assert balance_response.status == expected_status, (
            f"Expected status code {expected_status}, got {balance_response.status}"
        )
        return balance_response

    async def get_portfolio(self, expected_status: Optional[int] = 200):
        endpoint = "/public/portfolio"
        log.info(f"Getting portfolio via GET {endpoint}")
        start_time = time.monotonic()
        portfolio_response = await self.client.get(endpoint, timeout=ClientTimeout(total=self.get_timeout))
        self.update_stats('client.get' + ' - ' + endpoint, start_time)
        log.info(f"Response status code: {portfolio_response.status}")
        assert portfolio_response.status == expected_status, (
            f"Expected status code {expected_status}, got {portfolio_response.status}"
        )
        return portfolio_response

    async def get_user_info(self, expected_status: Optional[int] = 200):
        endpoint = "/public/user-info"
        log.info(f"Getting user info via GET {endpoint}")
        start_time = time.monotonic()
        user_info_response = await self.client.get(endpoint, timeout=ClientTimeout(total=self.get_timeout))
        self.update_stats('client.get' + ' - ' + endpoint, start_time)
        log.info(f"Response status code: {user_info_response.status}")
        assert user_info_response.status == expected_status, (
            f"Expected status code {expected_status}, got {user_info_response.status}"
        )
        return user_info_response

    async def get_contract_data(self, expected_status: Optional[int] = 200):
        endpoint = "/public/contract-data"
        log.info(f"Getting contract data via GET {endpoint}")
        start_time = time.monotonic()
        contract_data_response = await self.client.get(
            endpoint, timeout=ClientTimeout(total=self.get_timeout)
        )
        self.update_stats('client.get' + ' - ' + endpoint, start_time)
        log.info(f"Response status code: {contract_data_response.status}")
        assert contract_data_response.status == expected_status, (
            f"Expected status code {expected_status}, got {contract_data_response.status}"
        )
        return contract_data_response

    async def get_margin_data(self, expected_status: Optional[int] = 200):
        endpoint = "/public/margin-data"
        log.info(f"Getting margin data via GET {endpoint}")
        start_time = time.monotonic()
        margin_data_response = await self.client.get(
            endpoint, timeout=ClientTimeout(total=self.get_timeout)
        )
        self.update_stats('client.get' + ' - ' + endpoint, start_time)
        log.info(f"Response status code: {margin_data_response.status}")
        assert margin_data_response.status == expected_status, (
            f"Expected status code {expected_status}, got {margin_data_response.status}"
        )
        return margin_data_response

    async def get_markets(self, expected_status: Optional[int] = 200):
        endpoint = "/public/markets"
        log.info(f"Getting markets via GET {endpoint}")
        start_time = time.monotonic()
        markets_response = await self.client.get(
            endpoint, timeout=ClientTimeout(total=self.get_timeout)
        )
        self.update_stats('client.get' + ' - ' + endpoint, start_time)
        log.info(f"Response status code: {markets_response.status}")
        assert markets_response.status == expected_status, (
            f"Expected status code {expected_status}, got {markets_response.status}"
        )
        return markets_response

    async def get_transfers(self, expected_status: Optional[int] = 200):
        endpoint = "/public/transfers"
        log.info(f"Getting transfers via GET {endpoint}")
        start_time = time.monotonic()
        transfers_response = await self.client.get(
            endpoint, timeout=ClientTimeout(total=self.get_timeout)
        )
        self.update_stats('client.get' + ' - ' + endpoint, start_time)
        log.info(f"Response status code: {transfers_response.status}")
        assert transfers_response.status == expected_status, (
            f"Expected status code {expected_status}, got {transfers_response.status}"
        )
        return transfers_response

    async def get_funding(self, expected_status: Optional[int] = 200):
        endpoint = "/public/funding"
        log.info(f"Getting funding via GET {endpoint}")
        start_time = time.monotonic()
        funding_response = await self.client.get(
            endpoint, timeout=ClientTimeout(total=self.get_timeout)
        )
        self.update_stats('client.get' + ' - ' + endpoint, start_time)
        log.info(f"Response status code: {funding_response.status}")
        assert funding_response.status == expected_status, (
            f"Expected status code {expected_status}, got {funding_response.status}"
        )
        return funding_response

    async def get_trades(self, expected_status: Optional[int] = 200):
        endpoint = "/public/trades"
        log.info(f"Getting trades via GET {endpoint}")
        start_time = time.monotonic()
        trades_response = await self.client.get(
            endpoint, timeout=ClientTimeout(total=self.get_timeout)
        )
        self.update_stats('client.get' + ' - ' + endpoint, start_time)
        log.info(f"Response status code: {trades_response.status}")
        assert trades_response.status == expected_status, (
            f"Expected status code {expected_status}, got {trades_response.status}"
        )
        return trades_response
