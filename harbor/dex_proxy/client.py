from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any, Dict, Optional, List

import aiohttp

from .exceptions import HarborAPIError
from .utils import ensure_multiple


class HarborRESTClient:
    """Async Harbor REST client with tick validation, path fallbacks, and error enrichment."""

    def __init__(self, base_url: str, api_key: str, *, timeout: int | None = None):
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "X-API-KEY": api_key,
            "Content-Type": "application/json",
        }
        self._timeout = aiohttp.ClientTimeout(total=timeout) if timeout else None
        self._session: Optional[aiohttp.ClientSession] = None

        # Markets cache for tick validation
        self._markets: dict[str, dict[str, Any]] = {}
        self._markets_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------
    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ------------------------------------------------------------------
    # Low-level HTTP helpers
    # ------------------------------------------------------------------
    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[Any]:
        session = await self._ensure_session()
        url = f"{self._base_url}/{path.lstrip('/')}"
        async with session.request(method.upper(), url, headers=self._headers, params=params, json=json) as resp:
            return await self._json_or_error(resp)

    async def _request_try(
        self,
        method: str,
        paths: List[str],
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[Any]:
        """Try multiple candidate paths; fall back if 404, raise immediately otherwise."""
        last_exc: HarborAPIError | None = None
        for p in paths:
            try:
                return await self._request(method, p, params=params, json=json)
            except HarborAPIError as exc:
                if exc.status_code == 404:
                    last_exc = exc
                    continue
                raise
        raise last_exc or HarborAPIError(404, "All candidate endpoints returned 404")

    async def _json_or_error(self, resp: aiohttp.ClientResponse):
        try:
            data = await resp.json(content_type=None)
        except Exception:
            text = await resp.text()
            raise HarborAPIError(resp.status, f"Non-JSON response: {text}", request_id=None)

        if resp.status >= 400:
            request_id = self._extract_request_id(resp, data)
            message = self._extract_error_message(data)
            raise HarborAPIError(
                resp.status,
                message,
                request_id=request_id,
                payload=data if isinstance(data, dict) else None,
            )
        return data

    @staticmethod
    def _extract_request_id(resp: aiohttp.ClientResponse, payload: Any) -> str | None:
        if isinstance(payload, dict):
            for key in ("requestId", "request_id", "id"):
                if isinstance(payload.get(key), str):
                    return payload[key]
            error = payload.get("error")
            if isinstance(error, dict):
                for key in ("requestId", "request_id", "id"):
                    if isinstance(error.get(key), str):
                        return error[key]
        return resp.headers.get("X-Request-Id") or resp.headers.get("X-Request-ID")

    @staticmethod
    def _extract_error_message(payload: Any) -> str:
        if isinstance(payload, dict):
            if isinstance(payload.get("error"), dict):
                msg = payload["error"].get("message")
                if msg:
                    return str(msg)
            msg = payload.get("message")
            if msg:
                return str(msg)
        return str(payload)

    # ------------------------------------------------------------------
    # Market helpers
    # ------------------------------------------------------------------
    async def _get_market(self, instrument: str) -> dict[str, Any]:
        async with self._markets_lock:
            if instrument in self._markets:
                return self._markets[instrument]
            markets_payload = await self.get_markets()
            markets = markets_payload.get("markets") if isinstance(markets_payload, dict) else markets_payload
            if isinstance(markets, dict):
                markets = markets.get("markets", [])
            for m in markets or []:
                sym = m.get("symbol") or m.get("instrument")
                if sym:
                    self._markets[sym] = m
            if instrument not in self._markets:
                raise HarborAPIError(404, f"Instrument '{instrument}' not found", request_id=None)
            return self._markets[instrument]

    async def _validate_price_qty(
        self,
        instrument: str,
        *,
        price: str | float | Decimal | None,
        base_qty: str | float | Decimal | None,
        quote_qty: str | float | Decimal | None,
    ) -> None:
        market = await self._get_market(instrument)
        price_tick = Decimal(str(market.get("priceTick", "0")))
        qty_tick = Decimal(str(market.get("qtyTick", "0")))

        if price is not None:
            ensure_multiple(Decimal(str(price)), price_tick, field_name="price")
        if base_qty is not None:
            ensure_multiple(Decimal(str(base_qty)), qty_tick, field_name="base_qty")
        if quote_qty is not None and Decimal(str(quote_qty)) != Decimal("0"):
            if price_tick > 0 and qty_tick > 0:
                combined_tick = price_tick * qty_tick
                ensure_multiple(Decimal(str(quote_qty)), combined_tick, field_name="quote_qty")

    def clear_market_cache(self) -> None:
        self._markets.clear()

    # ------------------------------------------------------------------
    # Public endpoints
    # ------------------------------------------------------------------
    async def get_markets(self):
        # confirmed upstream path
        return await self._request("GET", "markets")

    async def get_account(self):
        # upstream is usually /account; keep private/account as fallback
        return await self._request_try("GET", ["account", "private/account"])

    async def get_depth(self, symbol: str):
        # common upstream: /orderbook/depth?symbol=...
        return await self._request_try("GET", ["orderbook/depth", "depth"], params={"symbol": symbol})

    async def get_orders(self, status: str = "open"):
        return await self._request_try("GET", ["orders", "private/orders"], params={"status": status})

    async def get_order(
        self,
        *,
        symbol: Optional[str] = None,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
    ):
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol
        if order_id:
            params["orderId"] = order_id
        if client_order_id:
            params["clientOrderId"] = client_order_id
        return await self._request_try("GET", ["order", "private/order"], params=params)

    async def cancel_order(
        self,
        *,
        symbol: Optional[str] = None,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
    ):
        payload: dict[str, Any] = {}
        if symbol:
            payload["symbol"] = symbol
        if order_id:
            payload["orderId"] = order_id
        if client_order_id:
            payload["clientOrderId"] = client_order_id
        return await self._request_try("DELETE", ["order", "private/order"], json=payload)

    async def create_order(self, payload: Dict[str, Any]):
        instrument = payload.get("symbol") or payload.get("instrument")
        if instrument:
            await self._validate_price_qty(
                instrument,
                price=payload.get("price"),
                base_qty=payload.get("qty") or payload.get("quantity"),
                quote_qty=None,
            )
        return await self._request_try("POST", ["order", "private/order"], json=payload)

    # ------------------------------------------------------------------
    # Spec-aligned endpoints
    # ------------------------------------------------------------------
    async def approve_token(
        self,
        *,
        client_request_id: str,
        token_symbol: str,
        amount: str | float | Decimal,
        spender_address: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "clientRequestId": client_request_id,
            "tokenSymbol": token_symbol,
            "amount": str(amount),
        }
        if spender_address:
            payload["spenderAddress"] = spender_address
        return await self._request_try("POST", ["approve-token", "private/approve-token"], json=payload)

    async def withdraw(
        self,
        *,
        client_request_id: str,
        token_symbol: str,
        amount: str | float | Decimal,
        destination: str,
    ) -> dict[str, Any]:
        payload = {
            "clientRequestId": client_request_id,
            "tokenSymbol": token_symbol,
            "amount": str(amount),
            "destination": destination,
        }
        return await self._request_try("POST", ["withdraw", "private/withdraw"], json=payload)

    async def insert_order(
        self,
        *,
        client_request_id: str,
        instrument: str,
        side: str,
        base_ccy_symbol: str,
        quote_ccy_symbol: str,
        order_type: str,
        price: str | float | Decimal | None,
        base_qty: str | float | Decimal | None,
        quote_qty: str | float | Decimal | None,
        time_in_force: str | None = None,
    ) -> dict[str, Any]:
        await self._validate_price_qty(instrument, price=price, base_qty=base_qty, quote_qty=quote_qty)
        payload: dict[str, Any] = {
            "clientRequestId": client_request_id,
            "instrument": instrument,
            "side": side,
            "baseCcySymbol": base_ccy_symbol,
            "quoteCcySymbol": quote_ccy_symbol,
            "orderType": order_type,
        }
        if price is not None:
            payload["price"] = str(price)
        if base_qty is not None:
            payload["baseQty"] = str(base_qty)
        if quote_qty is not None:
            payload["quoteQty"] = str(quote_qty)
        if time_in_force:
            payload["timeInForce"] = time_in_force
        return await self._request_try("POST", ["insert-order", "private/insert-order"], json=payload)

    async def amend_request(
        self,
        *,
        client_request_id: str | None,
        order_id: str | None,
        patch: Dict[str, Any],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            key: value
            for key, value in (("clientRequestId", client_request_id), ("orderId", order_id))
            if value is not None
        }
        patch_copy = dict(patch)
        instrument = patch_copy.get("instrument")
        price = patch_copy.get("price")
        base_qty = patch_copy.get("base_qty") or patch_copy.get("baseQty")
        quote_qty = patch_copy.get("quote_qty") or patch_copy.get("quoteQty")
        if instrument and (price is not None or base_qty is not None or quote_qty is not None):
            await self._validate_price_qty(instrument, price=price, base_qty=base_qty, quote_qty=quote_qty)
        payload["patch"] = self._normalise_patch(patch_copy)
        return await self._request_try("POST", ["amend-request", "private/amend-request"], json=payload)

    async def cancel_request(self, *, client_request_id: str) -> dict[str, Any]:
        return await self._request_try(
            "DELETE",
            ["cancel-request", "private/cancel-request"],
            params={"client_request_id": client_request_id},
        )

    async def cancel_all(self, *, request_type: str, instrument: str | None = None) -> dict[str, Any]:
        """
        Cancel all open requests of a given type (e.g., ORDER, WITHDRAW, APPROVE).
        Harbor API expects uppercase type in query param.
        """
        params: dict[str, Any] = {"type": str(request_type).upper()}
        if instrument:
            params["instrument"] = instrument

        try:
            return await self._request_try(
                "DELETE",
                ["private/cancel-all", "cancel-all"],
                params=params,
            )
        except Exception as exc:
            if "RequestType" in str(exc):
                raise TypeError(f"Invalid request_type format: {request_type}") from exc
            raise

    async def wrap_unwrap_token(
        self, *, client_request_id: str, symbol: str, amount: str | float | Decimal, action: str
    ) -> dict[str, Any]:
        payload = {
            "clientRequestId": client_request_id,
            "symbol": symbol,
            "amount": str(amount),
            "action": action,
        }
        return await self._request_try("POST", ["wrap-unwrap-token", "private/wrap-unwrap-token"], json=payload)

    async def get_all_open_requests(self, *, request_type: str) -> dict[str, Any] | list[Any]:
        return await self._request_try(
            "GET",
            ["requests/open", "public/get-all-open-requests"],
            params={"type": str(request_type).upper()},
        )

    async def get_request_status(self, *, client_request_id: str) -> dict[str, Any]:
        return await self._request_try(
            "GET",
            ["requests/status", "public/get-request-status"],
            params={"client_request_id": client_request_id},
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _normalise_patch(patch: Dict[str, Any]) -> Dict[str, Any]:
        normalised: Dict[str, Any] = {}
        for key, value in patch.items():
            if value is None:
                continue
            if key in {"base_qty", "baseQty", "quote_qty", "quoteQty", "price"}:
                normalised[key] = str(value)
            else:
                normalised[key] = value
        return normalised
