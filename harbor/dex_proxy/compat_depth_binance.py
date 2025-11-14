# harbor/dex_proxy/compat_depth_binance.py
from __future__ import annotations

import os
from typing import Dict, Any, Tuple, Optional
import aiohttp

# 直接 symbol->Binance 的映射（你当前 3 个交易对）
_SYMBOL_TO_BINANCE = {
    "eth.eth-eth.usdt": "ETHUSDT",
    "btc.btc-eth.usdt": "BTCUSDT",
    "eth.eth-btc.btc": "ETHBTC",
}

def _get_query(params: Dict[str, Any]) -> Dict[str, Any]:
    """兼容不同 WebServer 的参数承载方式."""
    if isinstance(params, dict):
        q = params.get("query")
        if isinstance(q, dict):
            return q
        return params
    return {}

def _instrument_to_binance_symbol(instr: str) -> Optional[str]:
    """
    把 instrument（如 harbor-ETH/USDT=0）转换为 Binance 符号（ETHUSDT）。
    规则：取 'BASE/QUOTE'，去掉斜杠并大写。
    """
    if not instr:
        return None
    s = instr.strip()
    # 允许前缀 'harbor-'，允许尾部 '=数字'
    if s.lower().startswith("harbor-"):
        s = s[len("harbor-"):]
    if "=" in s:
        s = s.split("=", 1)[0]
    # 现在 s 形如 'ETH/USDT' or 'BTC/USDT' or 'ETH/BTC'
    parts = s.split("/")
    if len(parts) != 2:
        return None
    base, quote = parts[0].strip().upper(), parts[1].strip().upper()
    return f"{base}{quote}"

def _symbol_to_binance_symbol(symbol: str) -> Optional[str]:
    """
    把 harbor 的 symbol（eth.eth-eth.usdt 等）映射到 Binance 符号。
    """
    if not symbol:
        return None
    key = symbol.strip().lower()
    return _SYMBOL_TO_BINANCE.get(key)

def make_binance_depth_handler():
    """
    兼容深度 handler：
      - 支持 ?symbol=eth.eth-eth.usdt
      - 也支持 ?instrument=harbor-ETH/USDT=0
    都会返回 Binance 标准的 {lastUpdateId,bids,asks}.
    """
    async def _handler(_path: str, params: Dict[str, Any], _t_ms: int) -> Tuple[int, Dict[str, Any]]:
        q = _get_query(params)
        symbol_q = (q.get("symbol") or "").strip()
        instr_q = (q.get("instrument") or "").strip()
        limit_raw = q.get("limit") or 5
        try:
            limit = int(limit_raw)
        except Exception:
            limit = 5

        # 先从 symbol 推断
        binance_symbol = None
        if symbol_q:
            binance_symbol = _symbol_to_binance_symbol(symbol_q)

        # 再尝试 instrument
        if not binance_symbol and instr_q:
            binance_symbol = _instrument_to_binance_symbol(instr_q)

        if not binance_symbol:
            return 400, {"error": {"message": "missing/unsupported 'symbol' or 'instrument'"}}

        base = os.getenv("BINANCE_BASE", "https://api.binance.us")

        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(f"{base}/api/v3/depth", params={"symbol": binance_symbol, "limit": limit}) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        return 502, {
                            "error": {
                                "message": "Binance depth fetch failed",
                                "status": resp.status,
                                "body": text[:500],
                                "binance_symbol": binance_symbol,
                            }
                        }
                    data = await resp.json()
                    # 直接透传 Binance 的 {lastUpdateId, bids, asks}
                    return 200, data
        except Exception as e:
            return 500, {"error": {"message": f"depth handler exception: {e.__class__.__name__}: {e}"}}

    return _handler

