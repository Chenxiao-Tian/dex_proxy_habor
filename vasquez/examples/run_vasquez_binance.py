#!/usr/bin/env python3
"""
Vasquez demo: fetch Binance top-of-book, align to Harbor ticks, and place a LIMIT order
with robust error handling and balance pre-check.

Usage (Windows CMD):
  set BINANCE_BASE=https://api.binance.us
  python -m vasquez.examples.run_vasquez_binance ^
    --base http://127.0.0.1:1958 ^
    --instrument eth.eth-eth.usdt ^
    --symbol ETHUSDT --side BUY --qty 0.001 --log-level INFO
"""
from __future__ import annotations

import os
import sys
import json
import argparse
import asyncio
import logging
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple, List

import aiohttp

try:
    # prefer your local client if present
    from vasquez.marketdata.binance_client import BinanceMarketDataClient
except Exception:
    # tiny fallback so the script is self-contained
    class BinanceMarketDataClient:
        def __init__(self, base: Optional[str] = None, session: Optional[aiohttp.ClientSession] = None):
            self.base = base or os.getenv("BINANCE_BASE") or "https://api.binance.com"
            self.session = session or aiohttp.ClientSession()

        async def _get(self, path: str, params: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
            url = self.base.rstrip("/") + path
            async with self.session.get(url, params=params, timeout=10) as resp:
                # Some regions (e.g. CN) return 451; prefer readable text on error
                text = await resp.text()
                if resp.status >= 400:
                    raise RuntimeError(f"GET {url} failed {resp.status}: {text}")
                try:
                    return json.loads(text)
                except Exception:
                    raise RuntimeError(f"GET {url} returned non-json: {text!r}")

        async def fetch_book_ticker(self, symbol: str) -> Dict[str, Any]:
            return await self._get("/api/v3/ticker/bookTicker", params={"symbol": symbol.upper()})

        async def close(self):
            if not self.session.closed:
                await self.session.close()


# --- util: tick alignment (kept here to avoid import drift) ---
from decimal import ROUND_FLOOR, ROUND_HALF_UP

def ensure_multiple(value: str | float | Decimal, tick: str | float | Decimal, mode: str = "floor") -> Decimal:
    """
    Align value to a multiple of tick.
    mode: "floor" (down) or "nearest" (ROUND_HALF_UP).
    """
    v = Decimal(str(value))
    t = Decimal(str(tick))
    if t <= 0:
        raise ValueError("tick must be > 0")

    q = v / t
    if mode in ("floor", "down"):
        q = q.to_integral_value(rounding=ROUND_FLOOR)
    elif mode in ("nearest", "round"):
        q = q.to_integral_value(rounding=ROUND_HALF_UP)
    else:
        raise ValueError(f"unknown mode={mode!r}")
    return (q * t).quantize(t)


def _decimalize(x: Any) -> Decimal:
    return Decimal(str(x))


def _pick_market(markets_payload: Dict[str, Any], instrument: Optional[str],
                 base: str, quote: str) -> Dict[str, Any]:
    markets = markets_payload.get("markets", {}).get("markets", [])
    if instrument:
        for m in markets:
            if m.get("symbol") == instrument:
                return m
        raise RuntimeError(f"Instrument {instrument!r} not found in markets.")
    # fallback by base/quote
    cand = [m for m in markets if m.get("baseAsset", "").startswith(base + ".")
            and m.get("quoteAsset", "").endswith(".USDT-0XDAC17F958D2EE523A2206206994597C13D831EC7")]
    if len(cand) == 1:
        return cand[0]
    if len(cand) > 1:
        raise RuntimeError(f"Multiple Harbor instruments match base={base} quote=USDT. Provide --instrument explicitly.")
    raise RuntimeError(f"No Harbor instrument matches base={base} quote=USDT.")


async def _http_get(session: aiohttp.ClientSession, base: str, path: str) -> Dict[str, Any]:
    url = base.rstrip("/") + path
    async with session.get(url, timeout=15) as resp:
        text = await resp.text()
        if resp.status >= 400:
            # best-effort parse json, else show raw text
            try:
                data = json.loads(text)
            except Exception:
                data = {"status": resp.status, "text": text}
            raise RuntimeError(f"GET {path} failed {resp.status}: {data}")
        try:
            return json.loads(text)
        except Exception:
            raise RuntimeError(f"GET {path} non-json: {text!r}")


async def _http_post(session: aiohttp.ClientSession, base: str, path: str, json_body: Dict[str, Any]) -> Dict[str, Any]:
    url = base.rstrip("/") + path
    async with session.post(url, json=json_body, timeout=20) as resp:
        text = await resp.text()
        # prefer readable failure even if server returns a pydantic object repr
        if resp.status >= 400:
            try:
                data = json.loads(text)
            except Exception:
                data = text
            raise RuntimeError(f"POST {path} failed {resp.status}: {data}")
        try:
            return json.loads(text)
        except Exception:
            return {"text": text, "status": resp.status}


INSERT_PATHS: Tuple[str, ...] = (
    "/private/insert-order",
    "/private/harbor/insert-order",
    "/private/create-order",
    "/private/harbor/create-order",
    "/private/harbor/create_order",  # alias some builds expose
)

async def _try_paths_post(session: aiohttp.ClientSession, base: str, paths: Tuple[str, ...], json_body: Dict[str, Any]) -> Dict[str, Any]:
    last_err: Optional[Exception] = None
    for p in paths:
        try:
            logging.info("POST %s %s", base, p)
            return await _http_post(session, base, p, json_body=json_body)
        except Exception as e:
            logging.warning("POST %s failed: %s", p, e)
            last_err = e
    assert last_err is not None
    raise last_err


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="dex-proxy base, e.g. http://127.0.0.1:1958")
    ap.add_argument("--instrument", required=False, help="Harbor instrument symbol, e.g. eth.eth-eth.usdt")
    ap.add_argument("--symbol", required=True, help="Binance symbol, e.g. ETHUSDT")
    ap.add_argument("--side", required=True, choices=["BUY", "SELL"])
    ap.add_argument("--qty", type=str, required=True, help="base qty to trade (string ok)")
    ap.add_argument("--price", type=str, required=False, help="optional limit price; if omitted, use best bid/ask")
    ap.add_argument("--tick-round", default="floor", choices=["floor", "nearest"], help="tick rounding mode")
    ap.add_argument("--log-level", default="INFO")
    ap.add_argument("--dry-run", action="store_true", help="only compute price/qty and exit without placing order")
    return ap.parse_args()


async def main() -> int:
    args = _parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(message)s")

    # 1) fetch markets & select instrument
    async with aiohttp.ClientSession() as session:
        markets_payload = await _http_get(session, args.base, "/public/harbor/get_markets")
        # If symbol looks like ETHUSDT, split it
        base_sym, quote_sym = args.symbol[:-4], args.symbol[-4:]
        m = _pick_market(markets_payload, args.instrument, base=base_sym, quote=quote_sym)
        logging.info("Selected Harbor instrument %s (base=%s quote=%s priceTick=%s qtyTick=%s)",
                     m["symbol"], m["baseAsset"], m["quoteAsset"], m["priceTick"], m["qtyTick"])
        price_tick = _decimalize(m["priceTick"])
        qty_tick = _decimalize(m["qtyTick"])

        # 2) get price from Binance if not provided
        if args.price:
            raw_price = _decimalize(args.price)
        else:
            md = BinanceMarketDataClient(session=session)
            ticker = await md.fetch_book_ticker(args.symbol.upper())
            bid = _decimalize(ticker["bidPrice"])
            ask = _decimalize(ticker["askPrice"])
            logging.info("Binance best bid=%s ask=%s", bid, ask)
            raw_price = bid if args.side == "BUY" else ask

        price = ensure_multiple(raw_price, price_tick, mode=args.tick_round)
        qty = ensure_multiple(args.qty, qty_tick, mode="floor")  # qty 一律向下取整
        logging.info("Tick-aligned price=%s qty=%s", price, qty)

        if args.dry_run:
            print(json.dumps({
                "instrument": m["symbol"],
                "side": args.side,
                "price": str(price),
                "base_qty": str(qty),
                "note": "dry-run only"
            }, indent=2))
            return 0

        # 3) pre-check balance; if empty, give a helpful message and exit
        bal = await _http_get(session, args.base, "/public/harbor/get_balance")
        exch = bal.get("balances", {}).get("exchange", [])
        if not exch:
            logging.warning("Your exchange balance is empty; Harbor will reject the order.")
            logging.warning("Action needed: deposit a small amount of USDT to the vault/router first, then retry.")
            return 2

        # 4) try posting to a few compatible endpoints
        body = {
            "client_request_id": f"vasquez-{os.getpid()}-{asyncio.get_running_loop().time()}",
            "instrument": m["symbol"],
            "side": args.side,
            "order_type": "LIMIT",
            "base_ccy_symbol": m["baseAsset"],
            "quote_ccy_symbol": m["quoteAsset"],
            "price": str(price),
            "base_qty": str(qty),
        }

        insert_resp = await _try_paths_post(session, args.base, INSERT_PATHS, json_body=body)
        print(json.dumps({"ok": True, "insert_response": insert_resp}, indent=2))
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
