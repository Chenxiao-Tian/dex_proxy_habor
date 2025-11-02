from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Tuple

import pytest

from harbor.dex_proxy.exceptions import HarborAPIError
from harbor.dex_proxy.harbor import Harbor


class _DummyServer:
    def __init__(self) -> None:
        self.registered: List[Tuple[Tuple[str, str], Dict[str, Any]]] = []

    def register(self, method: str, path: str, handler, **kwargs) -> None:
        self.registered.append(((method, path), kwargs))

    def deregister(self, method: str, path: str) -> None:  # pragma: no cover - optional path
        self.registered = [entry for entry in self.registered if entry[0] != (method, path)]


class _StubPantheon:
    process_name = "harbor-test"

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()


class _StubRestClient:
    def __init__(self) -> None:
        self.approve_payloads: List[Dict[str, Any]] = []
        self.withdraw_payloads: List[Dict[str, Any]] = []
        self.insert_payloads: List[Dict[str, Any]] = []
        self.amend_payloads: List[Dict[str, Any]] = []
        self.cancel_ids: List[str] = []
        self.cancel_all_params: List[Dict[str, Any]] = []
        self.wrap_payloads: List[Dict[str, Any]] = []
        self.request_status_queries: List[str] = []
        self.get_all_queries: List[str] = []
        self.error: HarborAPIError | None = None

    async def close(self) -> None:
        return None

    async def approve_token(self, **payload):
        if self.error:
            raise self.error
        self.approve_payloads.append(payload)
        return {"requestId": "req-approve", "status": "PENDING"}

    async def withdraw(self, **payload):
        if self.error:
            raise self.error
        self.withdraw_payloads.append(payload)
        return {"requestId": "req-withdraw", "status": "PENDING"}

    async def insert_order(self, **payload):
        if self.error:
            raise self.error
        base_qty = payload.get("base_qty")
        if base_qty is not None and str(base_qty) == "0.333":
            raise ValueError("base_qty does not respect tick")
        self.insert_payloads.append(payload)
        return {"requestId": "req-order", "status": "PENDING", "orderId": "abc123"}

    async def amend_request(self, **payload):
        if self.error:
            raise self.error
        self.amend_payloads.append(payload)
        return {"requestId": "req-amend", "status": "PENDING"}

    async def cancel_request(self, *, client_request_id: str):
        if self.error:
            raise self.error
        self.cancel_ids.append(client_request_id)
        return {"requestId": "req-cancel", "status": "PENDING"}

    async def cancel_all(self, **params):
        if self.error:
            raise self.error
        self.cancel_all_params.append(params)
        return {"requestId": "req-cancel-all", "status": "PENDING"}

    async def wrap_unwrap_token(self, **payload):
        if self.error:
            raise self.error
        self.wrap_payloads.append(payload)
        return {"requestId": "req-wrap", "status": "PENDING"}

    async def get_all_open_requests(self, *, request_type: str):
        if self.error:
            raise self.error
        self.get_all_queries.append(request_type)
        return {"requests": [{"clientRequestId": "demo"}]}

    async def get_request_status(self, *, client_request_id: str):
        if self.error:
            raise self.error
        self.request_status_queries.append(client_request_id)
        return {"requestId": "req-status", "status": "COMPLETED", "type": "ORDER"}

    async def get_orders(self, **_params):
        if self.error:
            raise self.error
        return []

    async def get_depth(self, symbol: str):
        if self.error:
            raise self.error
        return {"depth": {"symbol": symbol, "lastUpdateId": "10", "bids": [], "asks": []}}

    async def get_markets(self):  # pragma: no cover - not used in these tests
        return {"markets": []}


@pytest.fixture()
def harbor_connector():
    pantheon = _StubPantheon()
    server = _DummyServer()
    event_sink = object()
    config = {
        "name": "harbor",
        "rest": {"base_url": "https://example", "api_key": "dummy", "timeout": 1},
        "ws": {"url": "wss://example"},
        "request_cache": {"finalised_requests_cleanup_after_s": 1, "store_in_redis": False},
        "transactions_status_poller": {"poll_interval_s": 1},
    }
    stub_client = _StubRestClient()
    connector = Harbor(pantheon, config, server, event_sink, rest_client=stub_client)
    return connector, stub_client, server


def test_spec_routes_registered(harbor_connector):
    _, _, server = harbor_connector
    registered = {(method, path) for (method, path), _ in server.registered}
    expected_paths = {
        ("GET", "/public/status"),
        ("POST", "/private/approve-token"),
        ("POST", "/private/withdraw"),
        ("POST", "/private/insert-order"),
        ("POST", "/private/amend-request"),
        ("DELETE", "/private/cancel-request"),
        ("DELETE", "/private/cancel-all"),
        ("POST", "/private/wrap-unwrap-token"),
        ("GET", "/public/get-all-open-requests"),
        ("GET", "/public/get-request-status"),
    }
    assert expected_paths.issubset(registered)


def test_approve_token_returns_ack(harbor_connector):
    connector, stub, _ = harbor_connector
    status, body = asyncio.run(
        connector.approve_token(
            "/private/approve-token",
            {"client_request_id": "demo-approve", "token_symbol": "USDC", "amount": "1"},
            received_at_ms=0,
        )
    )

    assert status == 200
    assert body["request_id"] == "req-approve"
    assert body["status"].upper() == "PENDING"
    assert stub.approve_payloads[0]["token_symbol"] == "USDC"


def test_insert_order_enforces_tick(harbor_connector):
    connector, stub, _ = harbor_connector
    status, body = asyncio.run(
        connector.insert_order(
            "/private/insert-order",
            {
                "client_request_id": "order-1",
                "instrument": "btc",
                "side": "buy",
                "base_ccy_symbol": "BTC",
                "quote_ccy_symbol": "USDT",
                "order_type": "limit",
                "price": "10",
                "base_qty": "0.333",
            },
            received_at_ms=0,
        )
    )
    assert status == 400
    assert "tick" in body["error"]["message"].lower()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["type"] == "ORDER"
    assert body["error"]["client_request_id"] == "order-1"
    assert body["error"]["request_id"] is None

    status, body = asyncio.run(
        connector.insert_order(
            "/private/insert-order",
            {
                "client_request_id": "order-2",
            "instrument": "btc",
            "side": "buy",
            "base_ccy_symbol": "BTC",
            "quote_ccy_symbol": "USDT",
            "order_type": "limit",
            "price": "10",
            "base_qty": "0.1",
        },
        received_at_ms=0,
        )
    )
    assert status == 200
    assert body["order_id"] == "abc123"
    assert stub.insert_payloads[-1]["time_in_force"] == "gtc"


def test_get_request_status_response(harbor_connector):
    connector, stub, _ = harbor_connector
    status, body = asyncio.run(
        connector.get_request_status(
            "/public/get-request-status", {"client_request_id": "abc"}, received_at_ms=0
        )
    )

    assert status == 200
    assert body["client_request_id"] == "abc"
    assert body["status"] == "COMPLETED"
    assert stub.request_status_queries == ["abc"]


def test_error_response_propagates_request_id(harbor_connector):
    connector, stub, _ = harbor_connector
    stub.error = HarborAPIError(status_code=418, message="teapot", request_id="req-error")

    status, body = asyncio.run(
        connector.cancel_request(
            "/private/cancel-request", {"client_request_id": "abc"}, received_at_ms=0
        )
    )

    assert status == 418
    assert body["error"]["request_id"] == "req-error"
    assert body["error"]["code"] == 418
    assert body["error"]["type"] == "CANCEL"
    assert body["error"]["client_request_id"] == "abc"
    assert body["send_timestamp_ns"].isdigit()


def test_cancel_all_success(harbor_connector):
    connector, stub, _ = harbor_connector
    status, body = asyncio.run(
        connector.cancel_all(
            "/private/cancel-all", {"type": "order", "instrument": "btc"}, received_at_ms=0
        )
    )
    assert status == 200
    assert stub.cancel_all_params[-1] == {"request_type": "ORDER", "instrument": "btc"}
    assert body["type"] == "ORDER"


def test_cancel_all_404_returns_noop(harbor_connector):
    connector, stub, _ = harbor_connector
    stub.error = HarborAPIError(status_code=404, message="no cancel", request_id="req-404")

    status, body = asyncio.run(
        connector.cancel_all(
            "/private/cancel-all", {"type": "order"}, received_at_ms=0
        )
    )

    assert status == 200
    assert body["status"] == "NOOP"
    assert body["detail"]["reason"] == "upstream_cancel_all_not_available"
    assert body["request_id"] == "req-404"
    assert body["type"] == "ORDER"
    assert body["send_timestamp_ns"].isdigit()


def test_list_open_orders_returns_empty_on_404(harbor_connector):
    connector, stub, _ = harbor_connector
    stub.error = HarborAPIError(status_code=404, message="no orders")

    status, response = asyncio.run(
        connector.list_open_orders("/public/orders", {}, received_at_ms=0)
    )

    assert status == 200
    assert response.orders == []
    assert response.send_timestamp_ns > 0


def test_depth_404_returns_empty_snapshot(harbor_connector):
    connector, stub, _ = harbor_connector
    stub.error = HarborAPIError(status_code=404, message="no depth")

    status, body = asyncio.run(
        connector.get_depth_snapshot(
            "/public/depth", {"symbol": "eth.eth-eth.usdt"}, received_at_ms=0
        )
    )

    assert status == 200
    assert body["symbol"] == "eth.eth-eth.usdt"
    assert body["lastUpdateId"] == "0"
    assert body["bids"] == []
    assert body["asks"] == []
    assert body["send_timestamp_ns"].isdigit()
