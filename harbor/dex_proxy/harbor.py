# harbor/dex_proxy/harbor.py
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Optional, Tuple, Any, List

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

    def __init__(
        self,
        pantheon: Pantheon,
        config: dict,
        server: WebServer,
        event_sink,
        *,
        rest_client: HarborRESTClient | None = None,
    ):
        super().__init__(pantheon, config, server, event_sink)

        rest_cfg = config.get("rest", {})
        base_url = rest_cfg.get("base_url")
        if not base_url:
            raise ValueError("dex.rest.base_url must be configured for Harbor")

        api_key = rest_cfg.get("api_key")
        if not api_key:
            env_name = rest_cfg.get("api_key_env")
            if env_name:
                api_key = os.environ.get(env_name)
        if not api_key:
            raise ValueError("Harbor API key is not configured")

        self._rest_client = rest_client or HarborRESTClient(base_url=base_url, api_key=api_key)
        self._time_in_force = rest_cfg.get("default_time_in_force", "gtc")

        ws_cfg = config.get("ws", {})
        self._ws_url = ws_cfg.get("url")

        self._markets: Dict[str, Dict[str, Any]] = {}
        self._order_index: Dict[str, _OrderIndex] = {}

        self._register_endpoints(server)

    # ---------------------------
    # Route registration
    # ---------------------------
    def _register_endpoints(self, server: WebServer) -> None:
        # Health
        server.register("GET", "/ping", self._ping, summary="Health", tags=["public", "health"])

        # Debug: list routes
        server.register("GET", "/debug/routes", self._debug_routes, summary="List registered routes", tags=["debug"])

        # Markets (works today)
        for path in ("/public/markets", "/public/harbor/get_markets"):
            server.register(
                "GET",
                path,
                self.get_markets,
                summary="List Harbor markets",
                tags=["public", "market-data"],
                oapi_in=["harbor"],
            )

        # Account raw (may be 404 upstream in stagenet)
        server.register(
            "GET",
            "/public/account",
            self.get_account_raw,
            summary="Raw Harbor account payload",
            tags=["public", "account"],
            oapi_in=["harbor"],
        )

        # Balance (normalize; NEVER 404 from adapter)
        for path in (
            "/public/balance",
            "/public/harbor/get_balance",
            "/api/harbor/balance",
            "/private/balance",            # 兼容老脚本
            "/public/exchange_balance",    # 兼容别名
        ):
            server.register(
                "GET",
                path,
                self.get_balance,
                summary="Get account balances",
                tags=["public", "balance"],
                oapi_in=["harbor"],
            )

        # Create order
        create_order_kwargs = dict(
            request_model=CreateOrderRequest,
            response_model=OrderResponse,
            response_errors={400: {"model": OrderErrorResponse}},
            summary="Create order",
            tags=["private", "orders"],
            oapi_in=["harbor"],
        )
        for path in ("/private/create-order", "/private/harbor/create_order"):
            server.register("POST", path, self.create_order, **create_order_kwargs)

        # Cancel order
        cancel_order_kwargs = dict(
            request_model=CancelOrderParams,
            response_model=OrderResponse,
            response_errors={400: {"model": OrderErrorResponse}},
            summary="Cancel order",
            tags=["private", "orders"],
            oapi_in=["harbor"],
        )
        for method, path in (
            ("DELETE", "/private/cancel-order"),
            ("DELETE", "/private/harbor/cancel_order"),
            ("POST", "/private/harbor/cancel_order"),
        ):
            server.register(method, path, self.cancel_order, **cancel_order_kwargs)

        # List open orders
        list_orders_kwargs = dict(
            response_model=QueryLiveOrdersResponse,
            response_errors={400: {"model": OrderErrorResponse}},
            summary="List open orders",
            tags=["private", "orders"],
            oapi_in=["harbor"],
        )
        for path in ("/public/orders", "/private/harbor/list_open_orders"):
            server.register("GET", path, self.list_open_orders, **list_orders_kwargs)

        # Depth snapshot (upstream may be 404 in some envs)
        for path in ("/public/depth", "/public/harbor/get_depth_snapshot"):
            server.register(
                "GET",
                path,
                self.get_depth_snapshot,
                summary="Depth snapshot for a symbol",
                tags=["public", "market-data"],
                oapi_in=["harbor"],
            )

    # ---------------------------
    # Core handlers
    # ---------------------------
    async def _ping(self, path, params, received_at_ms):
        return 200, {"ok": True, "name": self._config.get("name", "harbor")}

    async def _debug_routes(self, path, params, received_at_ms):
        # WebServer keeps self._routes as a list of dicts
        routes = getattr(self._server, "_routes", [])
        return 200, {"routes": routes, "count": len(routes)}

    async def start(self, private_key=None):
        self.started = True

    async def stop(self) -> None:
        await self._rest_client.close()

    # Markets
    async def get_markets(self, path, params, received_at_ms):
        try:
            markets_payload = await self._rest_client.get_markets()
            # normalize cache
            self._markets.clear()
            for m in markets_payload.get("markets", markets_payload if isinstance(markets_payload, list) else []):
                sym = m.get("symbol")
                if sym:
                    self._markets[sym] = m
            return 200, {
                "count": len(self._markets),
                "markets": {"markets": list(self._markets.values())},
                "send_timestamp_ns": now_ns(),
            }
        except HarborAPIError as exc:
            return self._harbor_error(exc)

    # Account raw (diagnostic)
    async def get_account_raw(self, path, params, received_at_ms):
        try:
            payload = await self._rest_client.get_account()
            return 200, {"account": payload, "send_timestamp_ns": now_ns()}
        except HarborAPIError as exc:
            status, err = self._harbor_error(exc)
            # bubble upstream status for clarity
            return status, {**err.model_dump(), "upstream_status": getattr(exc, "status_code", status)}

    # Balance (NEVER 404; empty list if upstream not available)
    async def get_balance(self, path, params, received_at_ms) -> Tuple[int, Dict[str, Any]]:
        balances: List[Dict[str, str]] = []
        meta: Dict[str, Any] = {}
        try:
            payload = await self._rest_client.get_account()
            balances_payload = payload.get("balances") or payload.get("account", {}).get("balances", [])
            iterable = balances_payload.values() if isinstance(balances_payload, dict) else balances_payload
            for entry in iterable:
                symbol = entry.get("asset") or entry.get("symbol")
                bal = entry.get("total") or entry.get("available") or entry.get("balance") or "0"
                try:
                    bal = str(Decimal(str(bal)))
                except Exception:
                    bal = str(bal)
                if symbol:
                    balances.append({"symbol": symbol, "balance": bal})
        except HarborAPIError as exc:
            # Do not 404 – return empty but include diagnostic
            meta = {
                "warning": "upstream_error",
                "error": {"code": exc.status_code, "message": exc.message},
            }
        return 200, {"balances": {"exchange": balances}, **meta}

    # Create order
    async def create_order(self, path, params, received_at_ms) -> Tuple[int, OrderResponse | OrderErrorResponse]:
        request = CreateOrderRequest(**params)
        try:
            market = await self._get_market(request.symbol)
        except HarborAPIError as exc:
            return self._harbor_error(exc)
        except KeyError:
            return 400, OrderErrorResponse(error_code="UNKNOWN_SYMBOL", error_message=f"Symbol {request.symbol} is not listed on Harbor")

        try:
            price = ensure_multiple(Decimal(request.price), Decimal(market["priceTick"]), field_name="price")
            quantity = ensure_multiple(Decimal(request.quantity), Decimal(market["qtyTick"]), field_name="quantity")
        except ValueError as exc:
            return 400, OrderErrorResponse(error_code="INVALID_TICK", error_message=str(exc))

        body = {
            "symbol": request.symbol,
            "clientOrderId": request.client_order_id,
            "type": request.order_type.lower(),
            "side": request.side.lower(),
            "price": format(price, "f"),
            "qty": format(quantity, "f"),
            "timeInForce": self._time_in_force,
        }
        try:
            api_resp = await self._rest_client.create_order(body)
        except HarborAPIError as exc:
            return self._harbor_error(exc)

        order = api_resp.get("order", api_resp)
        resp = self._map_order(order, send_timestamp=now_ns())
        self._order_index[resp.client_order_id] = _OrderIndex(resp.symbol, resp.order_id)
        return 200, resp

    # Cancel order
    async def cancel_order(self, path, params, received_at_ms) -> Tuple[int, OrderResponse | OrderErrorResponse]:
        p = CancelOrderParams(**params)
        idx = self._order_index.get(p.client_order_id)
        symbol = idx.symbol if idx else None
        order_id = idx.order_id if idx else None
        try:
            await self._rest_client.cancel_order(symbol=symbol, order_id=order_id, client_order_id=p.client_order_id)
            order_payload = await self._rest_client.get_order(symbol=symbol, order_id=order_id, client_order_id=p.client_order_id)
        except HarborAPIError as exc:
            return self._harbor_error(exc)
        resp = self._map_order(order_payload.get("order", order_payload), send_timestamp=now_ns())
        self._order_index[p.client_order_id] = _OrderIndex(resp.symbol, resp.order_id)
        return 200, resp

    # List open orders
    async def list_open_orders(self, path, params, received_at_ms) -> Tuple[int, QueryLiveOrdersResponse | OrderErrorResponse]:
        try:
            payload = await self._rest_client.get_orders(status="open")
        except HarborAPIError as exc:
            return self._harbor_error(exc)

        ts = now_ns()
        orders = [self._map_order(o, send_timestamp=ts) for o in payload]
        for o in orders:
            self._order_index[o.client_order_id] = _OrderIndex(o.symbol, o.order_id)
        return 200, QueryLiveOrdersResponse(send_timestamp_ns=ts, orders=orders)

    # Depth snapshot
    async def get_depth_snapshot(self, path, params, received_at_ms):
        symbol = params.get("symbol") if isinstance(params, dict) else None
        if not symbol:
            return 400, {"error": {"message": "symbol parameter is required"}}
        try:
            depth_payload = await self._rest_client.get_depth(symbol)
            depth = depth_payload.get("depth", depth_payload)
            return 200, {
                "symbol": depth.get("symbol", symbol),
                "lastUpdateId": depth.get("lastUpdateId"),
                "bids": depth.get("bids", []),
                "asks": depth.get("asks", []),
                "send_timestamp_ns": now_ns(),
            }
        except HarborAPIError as exc:
            status, err = self._harbor_error(exc)
            return status, {**err.model_dump(), "upstream_status": getattr(exc, "status_code", status)}

    # ---------------------------
    # Abstracts required by DexCommon (no-op for Harbor spot HTTP)
    # ---------------------------
    async def on_new_connection(self, ws):  # pragma: no cover
        return

    async def process_request(self, ws, request_id, method, params: dict):  # pragma: no cover
        return False

    async def _approve(self, request, gas_price_wei, nonce=None):  # pragma: no cover
        raise NotImplementedError

    async def _transfer(self, request, gas_price_wei, nonce=None):  # pragma: no cover
        raise NotImplementedError

    async def _amend_transaction(self, request, params, gas_price_wei):  # pragma: no cover
        raise NotImplementedError

    async def _cancel_transaction(self, request, gas_price_wei):  # pragma: no cover
        raise NotImplementedError

    async def get_transaction_receipt(self, request, tx_hash):  # pragma: no cover
        return None

    def _get_gas_price(self, request, priority_fee: PriorityFee):  # pragma: no cover
        return None

    async def _get_all_open_requests(self, path, params, received_at_ms):  # pragma: no cover
        return await DexCommon._get_all_open_requests(self, path, params, received_at_ms)

    async def _cancel_all(self, path, params, received_at_ms):  # pragma: no cover
        return await DexCommon._cancel_all(self, path, params, received_at_ms)

    def on_request_status_update(
        self, client_order_id, request_status: RequestStatus, tx_receipt: dict, mined_tx_hash: str = None
    ):
        super().on_request_status_update(client_order_id, request_status, tx_receipt, mined_tx_hash)

    # ---------------------------
    # Helpers
    # ---------------------------
    async def _get_market(self, symbol: str) -> Dict[str, Any]:
        if symbol not in self._markets:
            markets_payload = await self._rest_client.get_markets()
            for m in markets_payload.get("markets", markets_payload if isinstance(markets_payload, list) else []):
                sym = m.get("symbol")
                if sym:
                    self._markets[sym] = m
        return self._markets[symbol]

    def _map_order(self, order_payload: Dict[str, Any], *, send_timestamp: int) -> OrderResponse:
        last_update = order_payload.get("updatedAt") or order_payload.get("createdAt") or "0"
        try:
            last_update_ns = int(last_update)
        except Exception:
            last_update_ns = now_ns()

        status = (order_payload.get("status") or "").upper()
        order_type = (order_payload.get("type") or order_payload.get("timeInForce") or "").upper()
        side = (order_payload.get("side") or "").upper()

        return OrderResponse(
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

    def _harbor_error(self, exc: HarborAPIError) -> Tuple[int, OrderErrorResponse]:
        request_part = f" (request_id={exc.request_id})" if exc.request_id else ""
        message = f"Harbor error{request_part}: {exc.message}"
        return exc.status_code, OrderErrorResponse(error_code="HARBOR_ERROR", error_message=message)
