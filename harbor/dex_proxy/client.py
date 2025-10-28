from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

import aiohttp

from .exceptions import HarborAPIError

_LOGGER = logging.getLogger(__name__)


@dataclass
class MarketInfo:
    symbol: str
    price_tick: str
    qty_tick: str

    @property
    def price_tick_decimal(self):
        from decimal import Decimal

        return Decimal(self.price_tick)

    @property
    def qty_tick_decimal(self):
        from decimal import Decimal

        return Decimal(self.qty_tick)


class HarborRESTClient:
    """Thin asynchronous wrapper around Harbor's REST API."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        session: aiohttp.ClientSession | None = None,
        request_timeout: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._session = session
        self._owns_session = session is None
        self._timeout = aiohttp.ClientTimeout(total=request_timeout)
        self._session_lock = asyncio.Lock()

    async def close(self) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            async with self._session_lock:
                if self._session is None:
                    self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        session = await self._ensure_session()
        headers = {"X-API-KEY": self._api_key, "accept": "application/json"}
        url = f"{self._base_url}{path}"
        _LOGGER.debug("Harbor request %s %s params=%s body=%s", method, url, params, json_body)

        async with session.request(
            method,
            url,
            params=params,
            json=json_body,
            headers=headers,
        ) as response:
            text = await response.text()
            try:
                payload = json.loads(text) if text else {}
            except json.JSONDecodeError:
                payload = {"raw": text}

            if response.status >= 400:
                message = payload.get("error") or payload.get("message") or text
                raise HarborAPIError(
                    response.status,
                    message=message or "Unknown Harbor error",
                    request_id=payload.get("requestId"),
                    payload=payload,
                )

            return payload

    async def get_account(self) -> Dict[str, Any]:
        return await self._request("GET", "/account")

    async def get_markets(self) -> Iterable[Dict[str, Any]]:
        payload = await self._request("GET", "/markets")
        return payload.get("markets", [])

    async def create_order(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return await self._request("POST", "/order", json_body=payload)

    async def cancel_order(
        self,
        *,
        symbol: str | None = None,
        order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol
        if order_id:
            params["orderId"] = order_id
        if client_order_id:
            params["clientOrderId"] = client_order_id
        return await self._request("DELETE", "/order", params=params)

    async def get_orders(self, *, status: str | None = None) -> Iterable[Dict[str, Any]]:
        params = {"status": status} if status else None
        payload = await self._request("GET", "/orders", params=params)
        return payload.get("orders", [])

    async def get_order(
        self,
        *,
        symbol: str | None = None,
        order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol
        if order_id:
            params["orderId"] = order_id
        if client_order_id:
            params["clientOrderId"] = client_order_id
        return await self._request("GET", "/order", params=params)

    async def get_depth(self, symbol: str) -> Dict[str, Any]:
        return await self._request("POST", f"/depth/{symbol}")

