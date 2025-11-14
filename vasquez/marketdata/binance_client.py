# vasquez/marketdata/binance_client.py
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import aiohttp


class BinanceMarketDataClient:
    """
    Very small REST client for Binance public market data.

    - Default base: https://api.binance.com
    - You can override by env var BINANCE_BASE (e.g., https://api.binance.us)
      or via constructor param `base`.
    """

    def __init__(
        self,
        base: Optional[str] = None,
        session: Optional[aiohttp.ClientSession] = None,
        timeout: float = 10.0,
    ) -> None:
        self.base = (base or os.getenv("BINANCE_BASE") or "https://api.binance.com").rstrip("/")
        self._session = session
        self._timeout = timeout

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self._timeout))
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        s = await self._ensure_session()
        url = f"{self.base}{path}"
        async with s.get(url, params=params) as resp:
            # Helpfully surface 451 (region blocked) with a clear hint
            if resp.status == 451:
                body = await resp.text()
                raise RuntimeError(
                    "Binance API returned 451 (region blocked). "
                    "Set BINANCE_BASE to a region you can access (e.g. https://api.binance.us). "
                    f"Body: {body[:200]}"
                )
            resp.raise_for_status()
            return await resp.json()

    async def fetch_book_ticker(self, symbol: str) -> Dict[str, Any]:
        """
        Returns the best bid/ask for a symbol:
        {
          "symbol": "ETHUSDT",
          "bidPrice": "3432.21",
          "bidQty": "0.301",
          "askPrice": "3442.23",
          "askQty": "0.218"
        }
        """
        symbol = symbol.upper()
        return await self._get("/api/v3/ticker/bookTicker", params={"symbol": symbol})
