import asyncio
import aiohttp
from typing import Any, Dict, Optional
from .exceptions import HarborAPIError


class HarborRESTClient:
    """
    Async REST client for Harbor DEX API.
    Lazy-creates aiohttp session inside the event loop.
    """

    def __init__(self, base_url: str, api_key: str):
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "X-API-KEY": api_key,
            "Content-Type": "application/json",
        }
        self._session: Optional[aiohttp.ClientSession] = None  # lazy init

    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Create ClientSession only when inside an event loop."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        """Close the session safely."""
        if self._session and not self._session.closed:
            await self._session.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    async def _json_or_error(self, resp: aiohttp.ClientResponse):
        try:
            data = await resp.json()
        except Exception:
            text = await resp.text()
            raise HarborAPIError(resp.status, f"Non-JSON response: {text}", request_id=None)

        if resp.status >= 400:
            err = data.get("error") if isinstance(data, dict) else None
            msg = (err or {}).get("message") or str(data)
            req_id = (err or {}).get("requestId")
            raise HarborAPIError(resp.status, msg, request_id=req_id)

        return data

    async def _get(self, path: str, params: Optional[Dict[str, Any]] = None):
        session = await self._ensure_session()
        url = f"{self._base_url}/{path.lstrip('/')}"
        async with session.get(url, headers=self._headers, params=params) as resp:
            return await self._json_or_error(resp)

    async def _post(self, path: str, json: Optional[Dict[str, Any]] = None):
        session = await self._ensure_session()
        url = f"{self._base_url}/{path.lstrip('/')}"
        async with session.post(url, headers=self._headers, json=json) as resp:
            return await self._json_or_error(resp)

    async def _delete(self, path: str, json: Optional[Dict[str, Any]] = None):
        session = await self._ensure_session()
        url = f"{self._base_url}/{path.lstrip('/')}"
        async with session.delete(url, headers=self._headers, json=json) as resp:
            return await self._json_or_error(resp)

    # ------------------------------------------------------------------
    # Harbor REST endpoints
    # ------------------------------------------------------------------
    async def get_account(self):
        return await self._get("private/account")

    async def get_markets(self):
        return await self._get("markets")

    async def get_orders(self, status: str = "open"):
        return await self._get("private/orders", params={"status": status})

    async def get_order(
        self, symbol: Optional[str] = None, order_id: Optional[str] = None, client_order_id: Optional[str] = None
    ):
        params = {}
        if symbol:
            params["symbol"] = symbol
        if order_id:
            params["orderId"] = order_id
        if client_order_id:
            params["clientOrderId"] = client_order_id
        return await self._get("private/order", params=params)

    async def cancel_order(
        self, symbol: Optional[str] = None, order_id: Optional[str] = None, client_order_id: Optional[str] = None
    ):
        payload = {}
        if symbol:
            payload["symbol"] = symbol
        if order_id:
            payload["orderId"] = order_id
        if client_order_id:
            payload["clientOrderId"] = client_order_id
        return await self._delete("private/order", json=payload)

    async def create_order(self, payload: Dict[str, Any]):
        return await self._post("private/order", json=payload)

    async def get_depth(self, symbol: str):
        return await self._get("depth", params={"symbol": symbol})


