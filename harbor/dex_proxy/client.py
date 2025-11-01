from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any, Dict, Optional

import aiohttp

from .exceptions import HarborAPIError
from .utils import ensure_multiple


class HarborRESTClient:
    """Async Harbor REST client with tick validation and error enrichment."""

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
    async def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                       json: dict[str, Any] | None = None) -> dict[str, Any] | list[Any]:
        session = await self._ensure_session()
        url = f"{self._base_url}/{path.lstrip('/')}"
        async with session.request(method.upper(), url, headers=self._headers, params=params, json=json) as resp:
            return await self._json_or_error(resp)

    async def _json_or_error(self, resp: aiohttp.ClientResponse):
        try:
            data = await resp.json()
        except Exception:
            text = await resp.text()
            raise HarborAPIError(resp.status, f"Non-JSON response: {text}", request_id=None)

        if resp.status >= 400:
            request_id = self._extract_request_id(resp, data)
            message = self._extract_error_message(data)
            raise HarborAPIError(resp.status, message, request_id=request_id, payload=data if isinstance(data, dict) else None)

        return data

    @staticmethod
    def _extract_request_id(resp: aiohttp.ClientResponse, payload: Any) -> str | None:
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
        header_value = resp.headers.get("X-Request-Id") or resp.headers.get("X-Request-ID")
        return header_value

    @staticmethod
    def _extract_error_message(payload: Any) -> str:
        if isinstance(payload, dict):
            error = payload.get("error") if isinstance(payload.get("error"), dict) else None
            if error:
                message = error.get("message")
                if message:
                    return str(message)
            message = payload.get("message")
            if message:
                return str(message)
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
            if not isinstance(markets, list):
                markets = []
            for market in markets:
                symbol = market.get("symbol") or market.get("instrument")
                if symbol:
                    self._markets[symbol] = market
            if instrument not in self._markets:
                raise HarborAPIError(404, f"Instrument '{instrument}' not found", request_id=None)
            return self._markets[instrument]

    async def _validate_price_qty(self, instrument: str, *, price: str | float | Decimal | None,
                                  base_qty: str | float | Decimal | None,
                                  quote_qty: str | float | Decimal | None) -> None:
        market = await self._get_market(instrument)
        price_tick = Decimal(str(market.get("priceTick", "0")))
        qty_tick = Decimal(str(market.get("qtyTick", "0")))

        if price is not None:
            ensure_multiple(Decimal(str(price)), price_tick, field_name="price")

        if base_qty is not None:
            ensure_multiple(Decimal(str(base_qty)), qty_tick, field_name="base_qty")

        if quote_qty is not None and Decimal(str(quote_qty)) != Decimal("0"):
            # Quote quantity validation is derived from price * qty tick size.
            combined_tick = (price_tick * qty_tick) if price_tick and qty_tick else None
            if combined_tick and combined_tick > 0:
                ensure_multiple(Decimal(str(quote_qty)), combined_tick, field_name="quote_qty")

    def clear_market_cache(self) -> None:
        self._markets.clear()

    # ------------------------------------------------------------------
    # Public endpoints
    # ------------------------------------------------------------------
    async def get_markets(self):
        return await self._request("GET", "markets")

    async def get_account(self):  # legacy support
        return await self._request("GET", "private/account")

    async def get_depth(self, symbol: str):  # legacy support
        return await self._request("GET", "depth", params={"symbol": symbol})

    async def get_orders(self, status: str = "open"):  # legacy support
        return await self._request("GET", "private/orders", params={"status": status})

    async def get_order(self, *, symbol: Optional[str] = None, order_id: Optional[str] = None,
                        client_order_id: Optional[str] = None):  # legacy support
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol
        if order_id:
            params["orderId"] = order_id
        if client_order_id:
            params["clientOrderId"] = client_order_id
        return await self._request("GET", "private/order", params=params)

    async def cancel_order(self, *, symbol: Optional[str] = None, order_id: Optional[str] = None,
                           client_order_id: Optional[str] = None):  # legacy support
        payload: dict[str, Any] = {}
        if symbol:
            payload["symbol"] = symbol
        if order_id:
            payload["orderId"] = order_id
        if client_order_id:
            payload["clientOrderId"] = client_order_id
        return await self._request("DELETE", "private/order", json=payload)

    async def create_order(self, payload: Dict[str, Any]):  # legacy support
        instrument = payload.get("symbol") or payload.get("instrument")
        if instrument:
            await self._validate_price_qty(
                instrument,
                price=payload.get("price"),
                base_qty=payload.get("qty") or payload.get("quantity"),
                quote_qty=None,
            )
        return await self._request("POST", "private/order", json=payload)

    # ------------------------------------------------------------------
    # Spec-aligned endpoints
    # ------------------------------------------------------------------
    async def approve_token(self, *, client_request_id: str, token_symbol: str, amount: str | float | Decimal,
                            spender_address: str | None = None) -> dict[str, Any]:
        payload = {
            "clientRequestId": client_request_id,
            "tokenSymbol": token_symbol,
            "amount": str(amount),
        }
        if spender_address:
            payload["spenderAddress"] = spender_address
        return await self._request("POST", "private/approve-token", json=payload)

    async def withdraw(self, *, client_request_id: str, token_symbol: str, amount: str | float | Decimal,
                       destination: str) -> dict[str, Any]:
        payload = {
            "clientRequestId": client_request_id,
            "tokenSymbol": token_symbol,
            "amount": str(amount),
            "destination": destination,
        }
        return await self._request("POST", "private/withdraw", json=payload)

    async def insert_order(self, *, client_request_id: str, instrument: str, side: str,
                           base_ccy_symbol: str, quote_ccy_symbol: str,
                           order_type: str, price: str | float | Decimal | None,
                           base_qty: str | float | Decimal | None,
                           quote_qty: str | float | Decimal | None,
                           time_in_force: str | None = None) -> dict[str, Any]:
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
        return await self._request("POST", "private/insert-order", json=payload)

    async def amend_request(self, *, client_request_id: str | None, order_id: str | None,
                            patch: Dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            key: value for key, value in (
                ("clientRequestId", client_request_id),
                ("orderId", order_id),
            ) if value is not None
        }
        patch_copy = dict(patch)
        instrument = patch_copy.get("instrument")
        price = patch_copy.get("price")
        base_qty = patch_copy.get("base_qty") or patch_copy.get("baseQty")
        quote_qty = patch_copy.get("quote_qty") or patch_copy.get("quoteQty")
        if instrument and (price is not None or base_qty is not None or quote_qty is not None):
            await self._validate_price_qty(
                instrument,
                price=price,
                base_qty=base_qty,
                quote_qty=quote_qty,
            )
        payload["patch"] = self._normalise_patch(patch_copy)
        return await self._request("POST", "private/amend-request", json=payload)

    async def cancel_request(self, *, client_request_id: str) -> dict[str, Any]:
        return await self._request("DELETE", "private/cancel-request", params={"client_request_id": client_request_id})

    async def cancel_all(self, *, request_type: str, instrument: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"type": request_type}
        if instrument:
            params["instrument"] = instrument
        return await self._request("DELETE", "private/cancel-all", params=params)

    async def wrap_unwrap_token(self, *, client_request_id: str, symbol: str,
                                amount: str | float | Decimal, action: str) -> dict[str, Any]:
        payload = {
            "clientRequestId": client_request_id,
            "symbol": symbol,
            "amount": str(amount),
            "action": action,
        }
        return await self._request("POST", "private/wrap-unwrap-token", json=payload)

    async def get_all_open_requests(self, *, request_type: str) -> dict[str, Any] | list[Any]:
        return await self._request("GET", "public/get-all-open-requests", params={"type": request_type})

    async def get_request_status(self, *, client_request_id: str) -> dict[str, Any]:
        return await self._request(
            "GET", "public/get-request-status", params={"client_request_id": client_request_id}
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


