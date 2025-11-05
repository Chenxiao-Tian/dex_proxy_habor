from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from pantheon import Pantheon

from py_dex_common.dexes.dex_common import DexCommon
from py_dex_common.schemas import (
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


# ---------------------------------------------------------------------------
# Request/response helpers for spec-aligned endpoints
# ---------------------------------------------------------------------------

class HarborRequestAck:
    def __init__(
        self,
        *,
        request_id: str,
        status: str,
        client_request_id: Optional[str],
        request_type: Optional[str],
        order_id: Optional[str],
        detail: Optional[Dict[str, Any]],
        send_timestamp_ns: str,
    ) -> None:
        self.request_id = request_id
        self.status = status
        self.client_request_id = client_request_id
        self.type = request_type
        self.order_id = order_id
        self.detail = detail
        self.send_timestamp_ns = send_timestamp_ns

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "request_id": self.request_id,
            "status": self.status,
            "send_timestamp_ns": self.send_timestamp_ns,
        }
        if self.client_request_id is not None:
            payload["client_request_id"] = self.client_request_id
        if self.type is not None:
            payload["type"] = self.type
        if self.order_id is not None:
            payload["order_id"] = self.order_id
        if self.detail:
            payload["detail"] = self.detail
        return payload


class HarborOpenRequestsResponse:
    def __init__(self, *, request_type: str, requests: List[Dict[str, Any]], send_timestamp_ns: str) -> None:
        self.type = request_type
        self.requests = requests
        self.count = len(requests)
        self.send_timestamp_ns = send_timestamp_ns

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "requests": self.requests,
            "count": self.count,
            "send_timestamp_ns": self.send_timestamp_ns,
        }


class HarborRequestStatusResponse:
    def __init__(
        self,
        *,
        client_request_id: str,
        request_type: str,
        status: str,
        detail: Optional[Dict[str, Any]],
        request_id: Optional[str],
        send_timestamp_ns: str,
    ) -> None:
        self.client_request_id = client_request_id
        self.type = request_type
        self.status = status
        self.detail = detail
        self.request_id = request_id
        self.send_timestamp_ns = send_timestamp_ns

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "client_request_id": self.client_request_id,
            "type": self.type,
            "status": self.status,
            "send_timestamp_ns": self.send_timestamp_ns,
        }
        if self.request_id is not None:
            payload["request_id"] = self.request_id
        if self.detail:
            payload["detail"] = self.detail
        return payload


def _require(params: Dict[str, Any], key: str) -> Any:
    if key not in params:
        raise ValueError(f"Missing field '{key}'")
    value = params[key]
    if isinstance(value, str) and not value.strip():
        raise ValueError(f"{key} must be provided")
    if value is None:
        raise ValueError(f"{key} must be provided")
    return value


def _optional_decimal(params: Dict[str, Any], key: str) -> Optional[Decimal]:
    if key not in params or params[key] is None:
        return None
    return Decimal(str(params[key]))


def _required_decimal(params: Dict[str, Any], key: str) -> Decimal:
    return Decimal(str(_require(params, key)))


def _normalize_action(value: str) -> str:
    lowered = value.lower()
    if lowered not in {"wrap", "unwrap"}:
        raise ValueError("action must be either 'wrap' or 'unwrap'")
    return lowered


def _normalize_type(value: str) -> str:
    if not value:
        raise ValueError("type must be provided")
    return value.upper()


@dataclass
class ApproveTokenBody:
    client_request_id: str
    token_symbol: str
    amount: Decimal
    spender_address: Optional[str]

    @classmethod
    def parse(cls, params: Dict[str, Any]) -> "ApproveTokenBody":
        client_request_id = str(_require(params, "client_request_id"))
        token_symbol = params.get("token_symbol") or params.get("symbol")
        token_symbol = str(_require({"token_symbol": token_symbol}, "token_symbol"))
        amount = _required_decimal(params, "amount")
        spender = params.get("spender_address")
        return cls(client_request_id, token_symbol, amount, spender)


@dataclass
class WithdrawBody:
    client_request_id: str
    token_symbol: str
    amount: Decimal
    destination: str

    @classmethod
    def parse(cls, params: Dict[str, Any]) -> "WithdrawBody":
        client_request_id = str(_require(params, "client_request_id"))
        token_symbol = params.get("token_symbol") or params.get("symbol")
        token_symbol = str(_require({"token_symbol": token_symbol}, "token_symbol"))
        amount = _required_decimal(params, "amount")
        destination = str(_require(params, "destination"))
        return cls(client_request_id, token_symbol, amount, destination)


@dataclass
class InsertOrderBody:
    client_request_id: str
    base_ccy_symbol: str
    quote_ccy_symbol: str
    instrument: str
    side: str
    order_type: str
    price: Optional[Decimal]
    base_qty: Optional[Decimal]
    quote_qty: Optional[Decimal]
    time_in_force: Optional[str]

    @classmethod
    def parse(cls, params: Dict[str, Any]) -> "InsertOrderBody":
        client_request_id = str(_require(params, "client_request_id"))
        base_ccy_symbol = str(_require(params, "base_ccy_symbol"))
        quote_ccy_symbol = str(_require(params, "quote_ccy_symbol"))
        instrument = str(_require(params, "instrument"))
        side = str(_require(params, "side")).upper()
        order_type = str(params.get("order_type", "LIMIT")).upper()
        price = _optional_decimal(params, "price")
        base_qty = _optional_decimal(params, "base_qty")
        quote_qty = _optional_decimal(params, "quote_qty")
        time_in_force = params.get("time_in_force")
        if base_qty is None and quote_qty is None:
            raise ValueError("Either base_qty or quote_qty must be provided")
        return cls(
            client_request_id,
            base_ccy_symbol,
            quote_ccy_symbol,
            instrument,
            side,
            order_type,
            price,
            base_qty,
            quote_qty,
            time_in_force,
        )


@dataclass
class AmendRequestBody:
    client_request_id: Optional[str]
    order_id: Optional[str]
    patch: Dict[str, Any]

    @classmethod
    def parse(cls, params: Dict[str, Any]) -> "AmendRequestBody":
        client_request_id = params.get("client_request_id")
        order_id = params.get("order_id")
        patch = params.get("patch")
        if not client_request_id and not order_id:
            raise ValueError("Either client_request_id or order_id must be provided")
        if not isinstance(patch, dict) or not patch:
            raise ValueError("patch must contain at least one field")
        return cls(client_request_id, order_id, patch)


@dataclass
class CancelRequestQuery:
    client_request_id: str

    @classmethod
    def parse(cls, params: Dict[str, Any]) -> "CancelRequestQuery":
        return cls(str(_require(params, "client_request_id")))


@dataclass
class CancelAllQuery:
    request_type: str
    instrument: Optional[str]

    @classmethod
    def parse(cls, params: Dict[str, Any]) -> "CancelAllQuery":
        raw = (params.get("request_type") or params.get("type") or "")
        request_type = _normalize_type(str(raw))
        instrument = params.get("instrument")
        return cls(request_type, instrument)


@dataclass
class WrapUnwrapBody:
    client_request_id: str
    symbol: str
    amount: Decimal
    action: str

    @classmethod
    def parse(cls, params: Dict[str, Any]) -> "WrapUnwrapBody":
        client_request_id = str(_require(params, "client_request_id"))
        symbol = str(_require(params, "symbol"))
        amount = _required_decimal(params, "amount")
        action = _normalize_action(str(_require(params, "action")))
        return cls(client_request_id, symbol, amount, action)


@dataclass
class GetAllOpenRequestsQuery:
    request_type: str

    @classmethod
    def parse(cls, params: Dict[str, Any]) -> "GetAllOpenRequestsQuery":
        raw = (params.get("request_type") or params.get("type") or "")
        return cls(_normalize_type(str(raw)))


@dataclass
class GetRequestStatusQuery:
    client_request_id: str

    @classmethod
    def parse(cls, params: Dict[str, Any]) -> "GetRequestStatusQuery":
        return cls(str(_require(params, "client_request_id")))


# ---------------------------------------------------------------------------
# Legacy helper for order tracking
# ---------------------------------------------------------------------------

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

        timeout = rest_cfg.get("timeout")
        self._rest_client = rest_client or HarborRESTClient(base_url=base_url, api_key=api_key, timeout=timeout)
        self._time_in_force = rest_cfg.get("default_time_in_force", "gtc")

        ws_cfg = config.get("ws", {})
        self._ws_url = ws_cfg.get("url")

        self._markets: Dict[str, Dict[str, Any]] = {}
        self._order_index: Dict[str, _OrderIndex] = {}

        # Wrapper preserved for backward compatibility
        self._register_endpoints(server)

    # ------------------------------------------------------------------
    # Backward-compatible registrar
    # ------------------------------------------------------------------
    def _register_endpoints(self, server: WebServer) -> None:
        """
        Older dex-proxy versions expect _register_endpoints() to exist.
        We keep all registrations here, delegating spec endpoints to the
        dedicated method to keep concerns separated.
        """
        # Health legacy (safe: not conflicting with default /public/status)
        server.register("GET", "/ping", self._ping, summary="Health", tags=["public", "health"])
        server.register("GET", "/debug/routes", self._debug_routes, summary="List registered routes", tags=["debug"])

        # Markets
        for path in ("/public/markets", "/public/harbor/get_markets"):
            server.register(
                "GET",
                path,
                self.get_markets,
                summary="List Harbor markets",
                tags=["public", "market-data"],
                oapi_in=["harbor"],
            )

        # Account raw
        server.register(
            "GET",
            "/public/account",
            self.get_account_raw,
            summary="Raw Harbor account payload",
            tags=["public", "account"],
            oapi_in=["harbor"],
        )

        # Balance (公开端点：错误时返回统一 envelope + 上游状态码)
        for path in (
            "/public/balance",
            "/public/harbor/get_balance",
            "/api/harbor/balance",
            "/private/balance",
            "/public/exchange_balance",
        ):
            server.register(
                "GET",
                path,
                self.get_balance,
                summary="Get account balances",
                tags=["public", "balance"],
                oapi_in=["harbor"],
            )

        # Legacy create/cancel/list orders — 兼容 dex-proxy 既有 Schema
        create_order_kwargs = dict(
            request_model=CreateOrderRequest,
            response_model=OrderResponse,
            response_errors={400: {"model": OrderErrorResponse}},
            summary="Create order (legacy)",
            tags=["private", "orders"],
            oapi_in=["harbor"],
        )
        server.register("POST", "/private/create-order", self.create_order, **create_order_kwargs)
        server.register("POST", "/private/harbor/create_order", self.create_order, **create_order_kwargs)

        cancel_order_kwargs = dict(
            request_model=CancelOrderParams,
            response_model=OrderResponse,
            response_errors={400: {"model": OrderErrorResponse}},
            summary="Cancel order (legacy)",
            tags=["private", "orders"],
            oapi_in=["harbor"],
        )
        for method, path in (
            ("DELETE", "/private/cancel-order"),
            ("DELETE", "/private/harbor/cancel_order"),
            ("POST", "/private/harbor/cancel_order"),
        ):
            server.register(method, path, self.cancel_order, **cancel_order_kwargs)

        list_orders_kwargs = dict(
            response_model=QueryLiveOrdersResponse,
            response_errors={400: {"model": OrderErrorResponse}},
            summary="List open orders (legacy)",
            tags=["private", "orders"],
            oapi_in=["harbor"],
        )
        server.register("GET", "/public/orders", self.list_open_orders, **list_orders_kwargs)
        server.register("GET", "/private/harbor/list_open_orders", self.list_open_orders, **list_orders_kwargs)

        # Depth snapshot
        for path in ("/public/depth", "/public/harbor/get_depth_snapshot"):
            server.register(
                "GET",
                path,
                self.get_depth_snapshot,
                summary="Depth snapshot for a symbol",
                tags=["public", "market-data"],
                oapi_in=["harbor"],
            )

        # Spec-aligned endpoints + harbor aliases
        self._register_spec_endpoints(server)

    def _register_spec_endpoints(self, server: WebServer) -> None:
        oapi = ["harbor"]

        # --- Requests: approve / withdraw / wrap-unwrap ---
        for path in ("/private/approve-token", "/private/harbor/approve-token"):
            server.register("POST", path, self.approve_token, summary="Approve token allowance on Harbor", tags=["private", "requests"], oapi_in=oapi)

        for path in ("/private/withdraw", "/private/harbor/withdraw"):
            server.register("POST", path, self.withdraw, summary="Withdraw funds from Harbor", tags=["private", "requests"], oapi_in=oapi)

        for path in ("/private/wrap-unwrap-token", "/private/harbor/wrap-unwrap-token"):
            server.register("POST", path, self.wrap_unwrap_token, summary="Wrap or unwrap native tokens", tags=["private", "requests"], oapi_in=oapi)

        # --- Orders: insert / amend / cancel ---
        for path in ("/private/insert-order", "/private/harbor/insert-order"):
            server.register("POST", path, self.insert_order, summary="Submit a spot order", tags=["private", "orders"], oapi_in=oapi)

        for path in ("/private/amend-request", "/private/harbor/amend-request"):
            server.register("POST", path, self.amend_request, summary="Amend an existing Harbor request", tags=["private", "orders"], oapi_in=oapi)

        for path in ("/private/cancel-request", "/private/harbor/cancel-request"):
            server.register("DELETE", path, self.cancel_request, summary="Cancel a request via client_request_id", tags=["private", "orders"], oapi_in=oapi)

        for path in ("/private/cancel-all", "/private/harbor/cancel-all"):
            server.register("DELETE", path, self.cancel_all, summary="Cancel all requests for a type", tags=["private", "orders"], oapi_in=oapi)

        # --- Requests: query open / status ---
        for path in ("/public/get-all-open-requests", "/public/harbor/get-all-open-requests"):
            server.register("GET", path, self.get_all_open_requests, summary="List Harbor open requests", tags=["public", "requests"], oapi_in=oapi)

        for path in ("/public/get-request-status", "/public/harbor/get-request-status"):
            server.register("GET", path, self.get_request_status, summary="Fetch Harbor request status", tags=["public", "requests"], oapi_in=oapi)

    # ------------------------------------------------------------------
    # Spec-aligned endpoint handlers
    # ------------------------------------------------------------------
    async def _status(self, path, params, received_at_ms):
        return 200, {"ok": True, "name": self._config.get("name", "harbor"), "send_timestamp_ns": str(now_ns())}

    async def approve_token(self, path, params, received_at_ms):
        try:
            body = ApproveTokenBody.parse(params)
        except ValueError as exc:
            return 400, self._validation_message(str(exc))

        try:
            api_response = await self._rest_client.approve_token(
                client_request_id=body.client_request_id,
                token_symbol=body.token_symbol,
                amount=body.amount,
                spender_address=body.spender_address,
            )
        except HarborAPIError as exc:
            return self._error_response("APPROVE", body.client_request_id, exc)

        ack = self._ack_response(api_response, request_type="APPROVE", client_request_id=body.client_request_id)
        return 200, ack.to_dict()

    async def withdraw(self, path, params, received_at_ms):
        try:
            body = WithdrawBody.parse(params)
        except ValueError as exc:
            return 400, self._validation_message(str(exc))

        try:
            api_response = await self._rest_client.withdraw(
                client_request_id=body.client_request_id,
                token_symbol=body.token_symbol,
                amount=body.amount,
                destination=body.destination,
            )
        except HarborAPIError as exc:
            return self._error_response("TRANSFER", body.client_request_id, exc)

        ack = self._ack_response(api_response, request_type="TRANSFER", client_request_id=body.client_request_id)
        return 200, ack.to_dict()

    async def insert_order(self, path, params, received_at_ms):
        try:
            body = InsertOrderBody.parse(params)
        except ValueError as exc:
            return 400, self._validation_message(str(exc))

        try:
            api_response = await self._rest_client.insert_order(
                client_request_id=body.client_request_id,
                instrument=body.instrument,
                side=body.side,
                base_ccy_symbol=body.base_ccy_symbol,
                quote_ccy_symbol=body.quote_ccy_symbol,
                order_type=body.order_type,
                price=body.price,
                base_qty=body.base_qty,
                quote_qty=body.quote_qty,
                time_in_force=body.time_in_force or self._time_in_force,
            )
        except HarborAPIError as exc:
            return self._error_response("ORDER", body.client_request_id, exc)
        except ValueError as exc:
            return 400, self._validation_message(str(exc))

        ack = self._ack_response(
            api_response,
            request_type="ORDER",
            client_request_id=body.client_request_id,
            extra_order_id=self._extract_order_id(api_response),
        )
        return 200, ack.to_dict()

    async def amend_request(self, path, params, received_at_ms):
        try:
            body = AmendRequestBody.parse(params)
        except ValueError as exc:
            return 400, self._validation_message(str(exc))

        try:
            api_response = await self._rest_client.amend_request(
                client_request_id=body.client_request_id,
                order_id=body.order_id,
                patch=body.patch,
            )
        except HarborAPIError as exc:
            return self._error_response("AMEND", body.client_request_id or body.order_id, exc)
        except ValueError as exc:
            return 400, self._validation_message(str(exc))

        ack = self._ack_response(api_response, request_type="AMEND", client_request_id=body.client_request_id)
        return 200, ack.to_dict()

    async def cancel_request(self, path, params, received_at_ms):
        try:
            query = CancelRequestQuery.parse(params)
        except ValueError as exc:
            return 400, self._validation_message(str(exc))

        try:
            api_response = await self._rest_client.cancel_request(client_request_id=query.client_request_id)
        except HarborAPIError as exc:
            return self._error_response("CANCEL", query.client_request_id, exc)

        ack = self._ack_response(api_response, request_type="CANCEL", client_request_id=query.client_request_id)
        return 200, ack.to_dict()

    async def cancel_all(self, path, params, received_at_ms):
        try:
            query = CancelAllQuery.parse(params)
        except ValueError as exc:
            return 400, self._validation_message(str(exc))

        try:
            api_response = await self._rest_client.cancel_all(
                request_type=query.request_type,
                instrument=query.instrument,
            )
        except HarborAPIError as exc:
            # 不再用 NOOP 掩盖上游不可用，直接透传错误
            return self._error_response("CANCEL", query.request_type, exc)

        ack = self._ack_response(api_response, request_type=query.request_type, client_request_id=None)
        return 200, ack.to_dict()

    async def wrap_unwrap_token(self, path, params, received_at_ms):
        try:
            body = WrapUnwrapBody.parse(params)
        except ValueError as exc:
            return 400, self._validation_message(str(exc))

        try:
            api_response = await self._rest_client.wrap_unwrap_token(
                client_request_id=body.client_request_id,
                symbol=body.symbol,
                amount=body.amount,
                action=body.action,
            )
        except HarborAPIError as exc:
            return self._error_response("WRAP_UNWRAP", body.client_request_id, exc)

        ack = self._ack_response(api_response, request_type="WRAP_UNWRAP", client_request_id=body.client_request_id)
        return 200, ack.to_dict()

    async def get_all_open_requests(self, path, params, received_at_ms):
        try:
            query = GetAllOpenRequestsQuery.parse(params)
        except ValueError as exc:
            return 400, self._validation_message(str(exc))

        try:
            api_response = await self._rest_client.get_all_open_requests(request_type=query.request_type)
        except HarborAPIError as exc:
            # 不再 200 空列表；按要求透传上游错误
            return self._error_response(query.request_type, None, exc)

        requests_payload = self._normalize_requests(api_response)
        response = HarborOpenRequestsResponse(
            request_type=query.request_type,
            requests=requests_payload,
            send_timestamp_ns=str(now_ns()),
        )
        return 200, response.to_dict()

    async def get_request_status(self, path, params, received_at_ms):
        try:
            query = GetRequestStatusQuery.parse(params)
        except ValueError as exc:
            return 400, self._validation_message(str(exc))

        try:
            api_response = await self._rest_client.get_request_status(client_request_id=query.client_request_id)
        except HarborAPIError as exc:
            return self._error_response("STATUS", query.client_request_id, exc)

        response = HarborRequestStatusResponse(
            client_request_id=query.client_request_id,
            request_type=str(api_response.get("type") or api_response.get("requestType", "UNKNOWN")),
            status=str(api_response.get("status", "UNKNOWN")),
            detail=self._extract_detail(api_response),
            request_id=self._extract_request_id(api_response),
            send_timestamp_ns=str(now_ns()),
        )
        return 200, response.to_dict()

    # ------------------------------------------------------------------
    # Legacy handlers retained for compatibility
    # ------------------------------------------------------------------
    async def _ping(self, path, params, received_at_ms):
        return 200, {"ok": True, "name": self._config.get("name", "harbor")}

    async def _debug_routes(self, path, params, received_at_ms):
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
            self._markets.clear()
            markets = markets_payload.get("markets", markets_payload if isinstance(markets_payload, list) else [])
            for market in markets:
                sym = market.get("symbol")
                if sym:
                    self._markets[sym] = market
            return 200, {
                "count": len(self._markets),
                "markets": {"markets": list(self._markets.values())},
                "send_timestamp_ns": str(now_ns()),
            }
        except HarborAPIError as exc:
            # 公开端点：统一错误 envelope
            return self._error_response("MARKETS", None, exc)

    async def get_account_raw(self, path, params, received_at_ms):
        try:
            payload = await self._rest_client.get_account()
            return 200, {"account": payload, "send_timestamp_ns": str(now_ns())}
        except HarborAPIError as exc:
            return self._error_response("ACCOUNT", None, exc)

    async def get_balance(self, path, params, received_at_ms) -> Tuple[int, Dict[str, Any]]:
        try:
            payload = await self._rest_client.get_account()
        except HarborAPIError as exc:
            # 公开端点：透传上游状态码 + 统一错误 envelope
            return self._error_response("BALANCE", None, exc)

        balances: List[Dict[str, str]] = []
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
        return 200, {"balances": {"exchange": balances}}

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

    async def get_depth_snapshot(self, path, params, received_at_ms):
        symbol = params.get("symbol") if isinstance(params, dict) else None
        if not symbol:
            return 400, {"error": {"message": "symbol parameter is required"}, "send_timestamp_ns": str(now_ns())}
        try:
            depth_payload = await self._rest_client.get_depth(symbol)
        except HarborAPIError as exc:
            # 不再返回空快照；按要求透传错误
            return self._error_response("DEPTH", symbol, exc)

        depth = depth_payload.get("depth", depth_payload)
        return 200, {
            "symbol": depth.get("symbol", symbol),
            "lastUpdateId": depth.get("lastUpdateId", "0"),
            "bids": depth.get("bids", []),
            "asks": depth.get("asks", []),
            "send_timestamp_ns": str(now_ns()),
        }

    # ------------------------------------------------------------------
    # DexCommon abstract requirements (unused for Harbor HTTP)
    # ------------------------------------------------------------------
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
        # Never call parent
        return await self.get_all_open_requests(path, params, received_at_ms)

    async def _cancel_all(self, path, params, received_at_ms):  # pragma: no cover
        # Never call parent
        return await self.cancel_all(path, params, received_at_ms)

    def on_request_status_update(
        self, client_order_id, request_status: RequestStatus, tx_receipt: dict, mined_tx_hash: str = None
    ):
        super().on_request_status_update(client_order_id, request_status, tx_receipt, mined_tx_hash)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _ack_response(
        self,
        api_response: Dict[str, Any] | List[Any],
        *,
        request_type: str,
        client_request_id: Optional[str],
        extra_order_id: Optional[str] = None,
    ) -> HarborRequestAck:
        request_id = self._extract_request_id(api_response) or ""
        detail = self._extract_detail(api_response)
        order_id = extra_order_id or self._extract_order_id(api_response)
        ack = HarborRequestAck(
            request_id=request_id,
            status=str(api_response.get("status", "PENDING") if isinstance(api_response, dict) else "PENDING"),
            client_request_id=client_request_id,
            request_type=request_type,
            order_id=order_id,
            detail=detail,
            send_timestamp_ns=str(now_ns()),
        )
        return ack

    @staticmethod
    def _extract_request_id(payload: Dict[str, Any] | List[Any] | None) -> Optional[str]:
        if isinstance(payload, dict):
            for key in ("requestId", "request_id", "id"):
                value = payload.get(key)
                if isinstance(value, str):
                    return value
            error = payload.get("error") if isinstance(payload.get("error"), dict) else None
            if error:
                for key in ("requestId", "request_id", "id"):
                    value = error.get(key)
                    if isinstance(value, str):
                        return value
        return None

    @staticmethod
    def _extract_order_id(payload: Dict[str, Any] | List[Any] | None) -> Optional[str]:
        if isinstance(payload, dict):
            for key in ("orderId", "order_id"):
                value = payload.get(key)
                if value is not None:
                    return str(value)
        return None

    @staticmethod
    def _extract_detail(payload: Dict[str, Any] | List[Any] | None) -> Optional[Dict[str, Any]]:
        if isinstance(payload, dict):
            ignored = {"status", "requestId", "request_id", "orderId", "order_id"}
            detail = {k: v for k, v in payload.items() if k not in ignored}
            return detail or None
        return None

    @staticmethod
    def _normalize_requests(payload: Dict[str, Any] | List[Any]) -> List[Dict[str, Any]]:
        if isinstance(payload, list):
            return [p if isinstance(p, dict) else {"value": p} for p in payload]
        if isinstance(payload, dict):
            items = payload.get("requests")
            if isinstance(items, list):
                return [item if isinstance(item, dict) else {"value": item} for item in items]
            return [payload]
        return []

    def _error_response(
        self,
        request_type: Optional[str],
        client_request_id: Optional[str],
        exc: HarborAPIError,
    ) -> Tuple[int, Dict[str, Any]]:
        send_ts = str(now_ns())
        message = exc.message or "Unknown Harbor error"
        payload = {
            "error": {
                "message": message,
                "code": exc.status_code,
                "request_id": exc.request_id,
                "type": request_type,
                "client_request_id": client_request_id,
            },
            "send_timestamp_ns": send_ts,
        }
        if exc.payload:
            payload["error"]["detail"] = exc.payload
        _LOGGER.warning(
            "Harbor API error for request_type=%s client_request_id=%s request_id=%s: %s",
            request_type,
            client_request_id,
            exc.request_id,
            message,
        )
        return exc.status_code or 500, payload

    @staticmethod
    def _validation_message(message: str) -> Dict[str, Any]:
        return {"error": {"message": message}, "send_timestamp_ns": str(now_ns())}

    async def _get_market(self, symbol: str) -> Dict[str, Any]:
        if symbol not in self._markets:
            markets_payload = await self._rest_client.get_markets()
            markets = markets_payload.get("markets", markets_payload if isinstance(markets_payload, list) else [])
            for market in markets:
                sym = market.get("symbol")
                if sym:
                    self._markets[sym] = market
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
        """
        Legacy-only error mapper for endpoints that are typed to OrderErrorResponse.
        (create_order / cancel_order / list_open_orders)
        """
        request_part = f" (request_id={exc.request_id})" if exc.request_id else ""
        message = f"Harbor error{request_part}: {exc.message}"
        return exc.status_code, OrderErrorResponse(error_code="HARBOR_ERROR", error_message=message)
