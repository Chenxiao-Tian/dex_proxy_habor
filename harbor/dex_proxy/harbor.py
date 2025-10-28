from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Optional, Tuple

from pantheon import Pantheon
from py_dex_common.dexes.dex_common import DexCommon
from py_dex_common.schemas import (
    BalanceItem,
    BalanceResponse,
    CancelOrderParams,
    CreateOrderRequest,
    OrderErrorResponse,
    OrderResponse,
    QueryLiveOrdersResponse,
)
from py_dex_common.web_server import WebServer
from pyutils.exchange_apis.dex_common import RequestStatus
from pyutils.gas_pricing.eth import PriorityFee

from .client import HarborRESTClient
from .exceptions import HarborAPIError
from .utils import ensure_multiple, now_ns

_LOGGER = logging.getLogger(__name__)


@dataclass
class _OrderIndex:
    symbol: Optional[str]
    order_id: Optional[str]


class Harbor(DexCommon):
    CHANNELS = ["orderbook.depth", "orderbook.trades", "orders", "balances"]

    def __init__(self, pantheon: Pantheon, config: dict, server: WebServer, event_sink, *, rest_client: HarborRESTClient | None = None):
        super().__init__(pantheon, config, server, event_sink)

        rest_config = config.get("rest", {})
        base_url = rest_config.get("base_url")
        if not base_url:
            raise ValueError("dex.rest.base_url must be configured for Harbor")

        api_key = rest_config.get("api_key")
        if not api_key:
            api_key_env = rest_config.get("api_key_env")
            if api_key_env:
                api_key = os.environ.get(api_key_env)
        if not api_key:
            raise ValueError("Harbor API key is not configured")

        self._rest_client = rest_client or HarborRESTClient(base_url=base_url, api_key=api_key)
        self._time_in_force = rest_config.get("default_time_in_force", "gtc")

        ws_config = config.get("ws", {})
        self._ws_url = ws_config.get("url")

        self._markets: Dict[str, Dict[str, str]] = {}
        self._order_index: Dict[str, _OrderIndex] = {}

        self._register_endpoints(server)

    def _register_endpoints(self, server: WebServer) -> None:
        server.register(
            "GET",
            "/public/balance",
            self.get_balance,
            response_model=BalanceResponse,
            summary="Get account balances from Harbor",
            tags=["public", "balance"],
            oapi_in=["harbor"],
        )

        server.register(
            "POST",
            "/private/create-order",
            self.create_order,
            request_model=CreateOrderRequest,
            response_model=OrderResponse,
            response_errors={400: {"model": OrderErrorResponse}},
            summary="Create a new Harbor order",
            tags=["private", "orders"],
            oapi_in=["harbor"],
        )

        server.register(
            "DELETE",
            "/private/cancel-order",
            self.cancel_order,
            request_model=CancelOrderParams,
            response_model=OrderResponse,
            response_errors={400: {"model": OrderErrorResponse}},
            summary="Cancel an existing Harbor order",
            tags=["private", "orders"],
            oapi_in=["harbor"],
        )

        server.register(
            "GET",
            "/public/orders",
            self.list_open_orders,
            response_model=QueryLiveOrdersResponse,
            response_errors={400: {"model": OrderErrorResponse}},
            summary="List open Harbor orders",
            tags=["public", "orders"],
            oapi_in=["harbor"],
        )

        server.register(
            "GET",
            "/public/depth",
            self.get_depth_snapshot,
            summary="Get depth snapshot for a Harbor symbol",
            tags=["public", "market-data"],
            oapi_in=["harbor"],
        )

    async def start(self, private_key=None):  # pragma: no cover - exercised in integration
        self.started = True

    async def stop(self) -> None:
        await self._rest_client.close()

    async def get_balance(self, path, params, received_at_ms) -> Tuple[int, BalanceResponse | OrderErrorResponse]:
        try:
            payload = await self._rest_client.get_account()
        except HarborAPIError as exc:
            return self._harbor_error(exc)

        balances_payload = payload.get("balances") or payload.get("account", {}).get("balances", [])
        if isinstance(balances_payload, dict):
            iterable = balances_payload.values()
        else:
            iterable = balances_payload

        account_balances = [
            BalanceItem(
                symbol=entry.get("asset") or entry.get("symbol"),
                balance=Decimal(entry.get("total") or entry.get("available") or entry.get("balance") or "0"),
            )
            for entry in iterable
        ]
        response = BalanceResponse(
            balances={"exchange": account_balances}
        )
        return 200, response

    async def create_order(self, path, params, received_at_ms) -> Tuple[int, OrderResponse | OrderErrorResponse]:
        request = CreateOrderRequest(**params)

        try:
            market = await self._get_market(request.symbol)
        except HarborAPIError as exc:
            return self._harbor_error(exc)
        except KeyError:
            return 400, OrderErrorResponse(
                error_code="UNKNOWN_SYMBOL",
                error_message=f"Symbol {request.symbol} is not listed on Harbor",
            )

        try:
            price = ensure_multiple(Decimal(request.price), Decimal(market["priceTick"]), field_name="price")
            quantity = ensure_multiple(Decimal(request.quantity), Decimal(market["qtyTick"]), field_name="quantity")
        except ValueError as exc:
            return 400, OrderErrorResponse(error_code="INVALID_TICK", error_message=str(exc))

        payload = {
            "symbol": request.symbol,
            "clientOrderId": request.client_order_id,
            "type": request.order_type.lower(),
            "side": request.side.lower(),
            "price": format(price, "f"),
            "qty": format(quantity, "f"),
            "timeInForce": self._time_in_force,
        }

        try:
            api_response = await self._rest_client.create_order(payload)
        except HarborAPIError as exc:
            return self._harbor_error(exc)

        order = api_response.get("order", api_response)
        order_response = self._map_order(order, send_timestamp=now_ns())
        self._order_index[order_response.client_order_id] = _OrderIndex(order_response.symbol, order_response.order_id)
        return 200, order_response

    async def cancel_order(self, path, params, received_at_ms) -> Tuple[int, OrderResponse | OrderErrorResponse]:
        cancel_params = CancelOrderParams(**params)
        index = self._order_index.get(cancel_params.client_order_id)
        symbol = index.symbol if index else None
        order_id = index.order_id if index else None

        try:
            await self._rest_client.cancel_order(
                symbol=symbol,
                order_id=order_id,
                client_order_id=cancel_params.client_order_id,
            )
            order_payload = await self._rest_client.get_order(
                symbol=symbol,
                order_id=order_id,
                client_order_id=cancel_params.client_order_id,
            )
        except HarborAPIError as exc:
            return self._harbor_error(exc)

        order_response = self._map_order(order_payload.get("order", order_payload), send_timestamp=now_ns())
        self._order_index[cancel_params.client_order_id] = _OrderIndex(order_response.symbol, order_response.order_id)
        return 200, order_response

    async def list_open_orders(self, path, params, received_at_ms) -> Tuple[int, QueryLiveOrdersResponse | OrderErrorResponse]:
        try:
            orders_payload = await self._rest_client.get_orders(status="open")
        except HarborAPIError as exc:
            return self._harbor_error(exc)

        current_timestamp = now_ns()
        orders = [self._map_order(raw_order, send_timestamp=current_timestamp) for raw_order in orders_payload]
        for order in orders:
            self._order_index[order.client_order_id] = _OrderIndex(order.symbol, order.order_id)

        return 200, QueryLiveOrdersResponse(send_timestamp_ns=current_timestamp, orders=orders)

    async def get_depth_snapshot(self, path, params, received_at_ms):
        symbol = params.get("symbol") if isinstance(params, dict) else None
        if not symbol:
            return 400, {"error": {"message": "symbol parameter is required"}}

        try:
            depth_payload = await self._rest_client.get_depth(symbol)
        except HarborAPIError as exc:
            status, error = self._harbor_error(exc)
            return status, error.model_dump()

        depth = depth_payload.get("depth", depth_payload)
        return 200, {
            "symbol": depth.get("symbol", symbol),
            "lastUpdateId": depth.get("lastUpdateId"),
            "bids": depth.get("bids", []),
            "asks": depth.get("asks", []),
            "send_timestamp_ns": now_ns(),
        }

    async def on_new_connection(self, ws):
        return

    async def process_request(self, ws, request_id, method, params: dict):
        return False

    async def _approve(self, request, gas_price_wei, nonce=None):
        raise NotImplementedError("Token approvals are not supported for Harbor")

    async def _transfer(self, request, gas_price_wei, nonce=None):
        raise NotImplementedError("Transfers are not implemented for Harbor")

    async def _amend_transaction(self, request, params, gas_price_wei):
        raise NotImplementedError("Transaction amendments are not supported for Harbor")

    async def _cancel_transaction(self, request, gas_price_wei):
        raise NotImplementedError("Transaction cancellation is not supported for Harbor")

    async def get_transaction_receipt(self, request, tx_hash):
        return None

    def _get_gas_price(self, request, priority_fee: PriorityFee):
        return None

    async def _get_all_open_requests(self, path, params, received_at_ms):
        return await DexCommon._get_all_open_requests(self, path, params, received_at_ms)

    async def _cancel_all(self, path, params, received_at_ms):
        return await DexCommon._cancel_all(self, path, params, received_at_ms)

    def on_request_status_update(self, client_request_id, request_status: RequestStatus, tx_receipt: dict, mined_tx_hash: str = None):
        super().on_request_status_update(client_request_id, request_status, tx_receipt, mined_tx_hash)

    async def _get_market(self, symbol: str) -> Dict[str, str]:
        if symbol not in self._markets:
            markets = await self._rest_client.get_markets()
            for market in markets:
                self._markets[market["symbol"]] = market
        return self._markets[symbol]

    def _map_order(self, order_payload: Dict[str, any], *, send_timestamp: int) -> OrderResponse:
        last_update = order_payload.get("updatedAt") or order_payload.get("createdAt") or "0"
        try:
            last_update_ns = int(last_update)
        except (ValueError, TypeError):
            last_update_ns = now_ns()

        status = (order_payload.get("status") or "").upper()
        order_type = (order_payload.get("type") or order_payload.get("timeInForce") or "").upper()
        side = (order_payload.get("side") or "").upper()

        response = OrderResponse(
            client_order_id=order_payload.get("clientOrderId") or order_payload.get("orderId"),
            order_id=str(order_payload.get("orderId")),
            price=str(order_payload.get("price")),
            quantity=str(order_payload.get("qty")),
            total_exec_quantity=str(order_payload.get("filledQty", order_payload.get("remainingQty", "0"))),
            last_update_timestamp_ns=last_update_ns,
            status=status,
            reason=order_payload.get("rejectReason"),
            trades=[],
            order_type=order_type or "LIMIT",
            symbol=order_payload.get("symbol"),
            side=side or "BUY",
            place_tx_id=str(order_payload.get("orderId")),
            send_timestamp_ns=send_timestamp,
        )
        return response

    def _harbor_error(self, exc: HarborAPIError) -> Tuple[int, OrderErrorResponse]:
        request_part = f" (request_id={exc.request_id})" if exc.request_id else ""
        message = f"Harbor error{request_part}: {exc.message}"
        return exc.status_code, OrderErrorResponse(error_code="HARBOR_ERROR", error_message=message)
