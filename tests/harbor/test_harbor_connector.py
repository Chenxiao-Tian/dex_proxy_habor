import asyncio
from decimal import Decimal

import pytest

from harbor.dex_proxy.exceptions import HarborAPIError
from harbor.dex_proxy.harbor import Harbor
from py_dex_common.schemas import OrderErrorResponse, OrderResponse, QueryLiveOrdersResponse


class DummyPantheon:
    process_name = "harbor-test"

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)


class DummyServer:
    def __init__(self):
        self.registered = []

    def register(self, *args, **kwargs):
        self.registered.append((args, kwargs))

    def send_json(self, ws, payload):  # pragma: no cover - compatibility hook
        raise NotImplementedError


class StubHarborClient:
    def __init__(self):
        self.markets = [
            {"symbol": "btc.btc-eth.usdt", "priceTick": "0.01", "qtyTick": "0.0001"}
        ]
        self.account_payload = {
            "balances": [
                {"asset": "BTC.BTC", "total": "1.5"},
                {"asset": "ETH.ETH", "available": "2"},
            ]
        }
        self.depth_payload = {"depth": {"symbol": "btc.btc-eth.usdt", "lastUpdateId": "42", "bids": [], "asks": []}}
        self.orders_created = []
        self.create_order_response = {
            "order": {
                "orderId": "101",
                "clientOrderId": "demo-1",
                "symbol": "btc.btc-eth.usdt",
                "price": "100000.00",
                "qty": "0.0002",
                "filledQty": "0",
                "status": "open",
                "type": "limit",
                "side": "buy",
                "createdAt": "1111111111111111111",
                "updatedAt": "1111111111111111111",
            }
        }
        self.order_payload = {
            "order": {
                "orderId": "101",
                "clientOrderId": "demo-1",
                "symbol": "btc.btc-eth.usdt",
                "price": "100000.00",
                "qty": "0.0002",
                "filledQty": "0",
                "status": "cancelled",
                "type": "limit",
                "side": "buy",
                "updatedAt": "2222222222222222222",
            }
        }
        self.orders_payload = [
            {
                "orderId": "102",
                "clientOrderId": "open-1",
                "symbol": "btc.btc-eth.usdt",
                "price": "99999.00",
                "qty": "0.0003",
                "filledQty": "0",
                "status": "open",
                "type": "limit",
                "side": "sell",
                "updatedAt": "3333333333333333333",
            }
        ]
        self.cancel_calls = []
        self.error: HarborAPIError | None = None

    def close(self):
        return None

    async def get_markets(self):
        if self.error:
            raise self.error
        return self.markets

    async def get_account(self):
        if self.error:
            raise self.error
        return self.account_payload

    async def create_order(self, payload):
        if self.error:
            raise self.error
        self.orders_created.append(payload)
        return self.create_order_response

    async def cancel_order(self, **kwargs):
        if self.error:
            raise self.error
        self.cancel_calls.append(kwargs)
        return {"orderId": kwargs.get("order_id")}

    async def get_order(self, **kwargs):
        if self.error:
            raise self.error
        return self.order_payload

    async def get_orders(self, **kwargs):
        if self.error:
            raise self.error
        return self.orders_payload

    async def get_depth(self, symbol: str):
        if self.error:
            raise self.error
        return self.depth_payload


@pytest.fixture()
def harbor_connector():
    pantheon = DummyPantheon()
    server = DummyServer()
    event_sink = object()
    config = {
        "name": "harbor",
        "rest": {"base_url": "https://example", "api_key": "dummy"},
        "ws": {"url": "wss://example"},
        "request_cache": {"finalised_requests_cleanup_after_s": 1, "store_in_redis": False},
        "transactions_status_poller": {"poll_interval_s": 1},
    }
    stub_client = StubHarborClient()
    connector = Harbor(pantheon, config, server, event_sink, rest_client=stub_client)
    connector._rest_client = stub_client  # type: ignore[attr-defined]
    return connector, stub_client, server


def test_route_registration(harbor_connector):
    connector, stub, server = harbor_connector
    registered = {(args[0], args[1]) for args, _ in server.registered}
    assert ("GET", "/ping") in registered
    assert ("GET", "/public/harbor/get_balance") in registered
    assert ("GET", "/public/balance") in registered
    assert ("POST", "/private/harbor/create_order") in registered
    assert ("POST", "/private/create-order") in registered
    assert ("DELETE", "/private/harbor/cancel_order") in registered
    assert ("POST", "/private/harbor/cancel_order") in registered
    assert ("GET", "/private/harbor/list_open_orders") in registered
    assert ("GET", "/public/harbor/get_depth_snapshot") in registered


def test_create_order_tick_validation(harbor_connector):
    connector, stub, _ = harbor_connector
    return connector, stub_client


def test_create_order_tick_validation(harbor_connector):
    connector, stub = harbor_connector
    params = {
        "client_order_id": "bad-tick",
        "symbol": "btc.btc-eth.usdt",
        "price": "100000.005",
        "quantity": "0.0002",
        "side": "BUY",
        "order_type": "LIMIT",
    }
    status, response = asyncio.run(connector.create_order("", params, 0))
    assert status == 400
    assert isinstance(response, OrderErrorResponse)
    assert "tick" in response.error_message
    assert stub.orders_created == []


def test_create_order_success(harbor_connector):
    connector, stub, _ = harbor_connector
    connector, stub = harbor_connector
    params = {
        "client_order_id": "demo-1",
        "symbol": "btc.btc-eth.usdt",
        "price": "100000.00",
        "quantity": "0.0002",
        "side": "BUY",
        "order_type": "LIMIT",
    }
    status, response = asyncio.run(connector.create_order("", params, 0))
    assert status == 200
    assert isinstance(response, OrderResponse)
    assert response.client_order_id == "demo-1"
    assert response.status == "OPEN"
    assert stub.orders_created[0]["timeInForce"] == "gtc"


def test_cancel_order_fetches_latest_state(harbor_connector):
    connector, stub, _ = harbor_connector
    connector, stub = harbor_connector
    connector._order_index["demo-1"] = None  # ensure mapping exists without symbol
    status, response = asyncio.run(connector.cancel_order("", {"client_order_id": "demo-1"}, 0))
    assert status == 200
    assert isinstance(response, OrderResponse)
    assert response.status == "CANCELLED"
    assert stub.cancel_calls[0]["client_order_id"] == "demo-1"


def test_list_open_orders_returns_snapshot(harbor_connector):
    connector, stub, _ = harbor_connector
    connector, stub = harbor_connector
    status, response = asyncio.run(connector.list_open_orders("", {}, 0))
    assert status == 200
    assert isinstance(response, QueryLiveOrdersResponse)
    assert len(response.orders) == 1
    assert response.orders[0].status == "OPEN"


def test_get_balance_handles_various_keys(harbor_connector):
    connector, stub, _ = harbor_connector
    connector, stub = harbor_connector
    stub.account_payload = {"balances": {"btc": {"asset": "BTC.BTC", "balance": "1.23"}}}
    status, response = asyncio.run(connector.get_balance("", {}, 0))
    assert status == 200
    assert response.balances["exchange"][0].balance == Decimal("1.23")


def test_get_depth_requires_symbol(harbor_connector):
    connector, stub, _ = harbor_connector
    connector, stub = harbor_connector
    status, response = asyncio.run(connector.get_depth_snapshot("", {}, 0))
    assert status == 400
    assert "symbol" in response["error"]["message"]


def test_error_bubbles_request_id(harbor_connector):
    connector, stub, _ = harbor_connector
    connector, stub = harbor_connector
    stub.error = HarborAPIError(401, "unauthorized", request_id="abc-123")
    status, response = asyncio.run(connector.get_balance("", {}, 0))
    assert status == 401
    assert isinstance(response, OrderErrorResponse)
    assert "abc-123" in response.error_message
