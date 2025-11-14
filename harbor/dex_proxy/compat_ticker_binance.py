# harbor/dex_proxy/compat_ticker_binance.py
from __future__ import annotations

import os
from typing import Dict, Any, Tuple, Optional
import aiohttp

_SYMBOL_TO_BINANCE = {
    "eth.eth-eth.usdt": "ETHUSDT",
    "btc.btc-eth.usdt": "BTCUSDT",
    "eth.eth-btc.btc": "ETHBTC",
}

def _get_query(params: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(params, dict):
        q = params.get("query")
        if isinstance(q, dict):
            return q
        return params
    return {}

def _instrument_to_binance_symbol(instr: str) -> Optional[str]:
    if not instr:
        return None
    s = instr.strip()
    if s.lower().startswith("harbor-"):
        s = s[len("harbor-"):]
    if "=" in s:
        s = s.split("=", 1)[0]
    if "/" in s:
        base, quote = s.split("/", 1)
        return (base.strip() + quote.strip()).upper()
    return None

def _symbol_to_binance_symbol(symbol: str) -> Optional[str]:
    if not symbol:
        return None
    return _SYMBOL_TO_BINANCE.get(symbol.strip().lower())

def make_binance_ticker_handler():
    """
    统一 /public/ticker：
      /public/ticker?symbol=eth.eth-eth.usdt
      /public/ticker?instrument=harbor-ETH/USDT=0
    返回 {symbol,bidPrice,askPrice}
    """
    async def _handler(_path: str, params: Dict[str, Any], _t_ms: int) -> Tuple[int, Dict[str, Any]]:
        q = _get_query(params)
        symbol_q = (q.get("symbol") or "").strip()
        instr_q  = (q.get("instrument") or "").strip()

        binance_symbol = _symbol_to_binance_symbol(symbol_q) or _instrument_to_binance_symbol(instr_q)
        if not binance_symbol:
            return 400, {"error": {"message": "missing/unsupported 'symbol' or 'instrument'"}}

        base = os.getenv("BINANCE_BASE", "https://api.binance.us")
        url  = f"{base}/api/v3/ticker/bookTicker"

        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(url, params={"symbol": binance_symbol}) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        return 502, {"error": {"message": "Binance ticker failed",
                                               "status": resp.status,
                                               "body": text[:500],
                                               "binance_symbol": binance_symbol}}
                    data = await resp.json()
                    return 200, {
                        "symbol": data.get("symbol", binance_symbol),
                        "bidPrice": data.get("bidPrice"),
                        "askPrice": data.get("askPrice"),
                    }
        except Exception as e:
            return 500, {"error": {"message": f"ticker handler exception: {e.__class__.__name__}: {e}"}}

    return _handler
