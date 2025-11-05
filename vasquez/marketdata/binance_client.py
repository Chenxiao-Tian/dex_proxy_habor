"""Lightweight Binance Spot REST client for fetching market data."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Iterable, Optional

import aiohttp

__all__ = ["BinanceClient"]

_LOGGER = logging.getLogger(__name__)


class BinanceClient:
    """Minimal async REST client for Binance Spot public data."""

    def __init__(self, *, session: aiohttp.ClientSession | None = None, base_url: str = "https://api.binance.com") -> None:
        self._base_url = base_url.rstrip("/")
        self._session = session
        self._own_session = session is None

    async def __aenter__(self) -> "BinanceClient":
        if self._session is None:
            self._session = aiohttp.ClientSession()
            self._own_session = True
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        await self.close()

    async def close(self) -> None:
        if self._own_session and self._session is not None and not self._session.closed:
            await self._session.close()
            self._session = None
            self._own_session = False

    async def _get(self, path: str, *, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if self._session is None:
            self._session = aiohttp.ClientSession()
            self._own_session = True
        url = f"{self._base_url}{path}"
        _LOGGER.debug("GET %s params=%s", url, params)
        async with self._session.get(url, params=params) as response:
            response.raise_for_status()
            return await response.json()

    async def fetch_book_ticker(self, symbol: str) -> Dict[str, Any]:
        """Return best bid/ask for the given symbol."""
        payload = await self._get("/api/v3/ticker/bookTicker", params={"symbol": symbol.upper()})
        return payload

    async def fetch_recent_klines(
        self,
        symbol: str,
        *,
        interval: str = "1m",
        limit: int = 10,
    ) -> Iterable[list[Any]]:
        """Return recent klines; mostly for debugging expected price ranges."""
        data = await self._get(
            "/api/v3/klines",
            params={"symbol": symbol.upper(), "interval": interval, "limit": str(limit)},
        )
        return data


async def _demo(symbol: str = "ETHUSDT") -> None:  # pragma: no cover - helper for manual testing
    async with BinanceClient() as client:
        ticker = await client.fetch_book_ticker(symbol)
        _LOGGER.info("%s: best_bid=%s best_ask=%s", symbol, ticker.get("bidPrice"), ticker.get("askPrice"))


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_demo())
