"""Run Vasquez against the Harbor dex-proxy using Binance Spot market data."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Iterable, Optional, Tuple

import aiohttp

from harbor.dex_proxy.utils import ensure_multiple, now_ns

from vasquez.marketdata.binance_client import BinanceClient

_LOGGER = logging.getLogger("vasquez.examples.run_vasquez_binance")

SUPPORTED_QUOTES = ("USDT", "USDC", "FDUSD", "TUSD", "BUSD", "BTC")


@dataclass
class HarborMarket:
    instrument: str
    base_symbol: str
    quote_symbol: str
    price_tick: Decimal
    qty_tick: Decimal


def _split_symbol(symbol: str) -> Tuple[str, str]:
    symbol_upper = symbol.upper().replace("/", "")
    for quote in SUPPORTED_QUOTES:
        if symbol_upper.endswith(quote):
            base = symbol_upper[: -len(quote)]
            if not base:
                break
            return base, quote
    raise ValueError(f"Unable to split symbol '{symbol}'. Provide --base-symbol/--quote-symbol explicitly.")


def _extract_markets(payload: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    markets = payload.get("markets")
    if isinstance(markets, dict):
        inner = markets.get("markets")
        if isinstance(inner, list):
            return inner
    if isinstance(markets, list):
        return markets
    if isinstance(payload, list):
        return payload
    return []


def _normalise_symbol(value: Optional[str]) -> str:
    return (value or "").strip()


def _match_market(candidate: Dict[str, Any], base: str, quote: str) -> bool:
    base = base.upper()
    quote = quote.upper()
    base_fields = [
        candidate.get("baseCcySymbol"),
        candidate.get("baseSymbol"),
        candidate.get("baseAsset"),
    ]
    quote_fields = [
        candidate.get("quoteCcySymbol"),
        candidate.get("quoteSymbol"),
        candidate.get("quoteAsset"),
    ]
    symbol = _normalise_symbol(candidate.get("symbol") or candidate.get("instrument"))
    symbol_upper = symbol.upper()
    base_fields.extend(part for part in symbol_upper.replace("-", ".").split(".") if part)
    quote_fields.extend(part for part in symbol_upper.replace("-", ".").split(".") if part)
    return base in {f.upper() for f in base_fields if isinstance(f, str)} and quote in {
        f.upper() for f in quote_fields if isinstance(f, str)
    }


def _select_market(payload: Dict[str, Any], *, instrument: Optional[str], base: str, quote: str) -> HarborMarket:
    markets = list(_extract_markets(payload))
    if not markets:
        raise RuntimeError("Harbor markets payload is empty; confirm the proxy is running and the API key is valid.")

    chosen: Optional[Dict[str, Any]] = None
    if instrument:
        for market in markets:
            symbol = _normalise_symbol(market.get("symbol") or market.get("instrument"))
            if symbol.lower() == instrument.lower():
                chosen = market
                break
    if chosen is None:
        matches = [m for m in markets if _match_market(m, base, quote)]
        if len(matches) == 1:
            chosen = matches[0]
        elif len(matches) > 1:
            raise RuntimeError(
                f"Multiple Harbor instruments match base={base} quote={quote}. Provide --instrument explicitly."
            )
    if chosen is None:
        raise RuntimeError(
            f"No Harbor instrument found for base={base} quote={quote}. Use --instrument to select one manually."
        )

    instrument_name = _normalise_symbol(chosen.get("symbol") or chosen.get("instrument"))
    try:
        price_tick = Decimal(str(chosen.get("priceTick")))
        qty_tick = Decimal(str(chosen.get("qtyTick")))
    except Exception as exc:  # pragma: no cover - defensive guard for unexpected payloads
        raise RuntimeError(f"Harbor market entry is missing tick data: {json.dumps(chosen, indent=2)}") from exc

    base_symbol = _normalise_symbol(
        chosen.get("baseCcySymbol") or chosen.get("baseSymbol") or chosen.get("baseAsset") or base
    )
    quote_symbol = _normalise_symbol(
        chosen.get("quoteCcySymbol") or chosen.get("quoteSymbol") or chosen.get("quoteAsset") or quote
    )

    return HarborMarket(
        instrument=instrument_name,
        base_symbol=base_symbol.upper(),
        quote_symbol=quote_symbol.upper(),
        price_tick=price_tick,
        qty_tick=qty_tick,
    )


def _align_price(raw_price: Decimal, *, tick: Decimal, side: str) -> Decimal:
    adjusted = ensure_multiple(raw_price, tick, field_name="price")
    if side == "SELL" and adjusted < raw_price:
        adjusted += tick
    if adjusted <= 0:
        adjusted = tick
    return adjusted


def _align_qty(raw_qty: Decimal, *, tick: Decimal) -> Decimal:
    adjusted = ensure_multiple(raw_qty, tick, field_name="quantity")
    if adjusted <= 0:
        raise ValueError("Quantity rounds down to zero with current qtyTick. Increase --qty.")
    return adjusted


def _extract_request_id(payload: Any) -> Optional[str]:
    if isinstance(payload, dict):
        for key in ("request_id", "requestId", "id"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
        error = payload.get("error")
        if isinstance(error, dict):
            for key in ("request_id", "requestId", "id"):
                value = error.get(key)
                if isinstance(value, str):
                    return value
    return None


async def _http_get(session: aiohttp.ClientSession, base: str, path: str, *, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"{base.rstrip('/')}{path}"
    _LOGGER.info("GET %s params=%s", url, params)
    async with session.get(url, params=params) as resp:
        payload = await resp.json()
        _LOGGER.info("<- %s status=%s request_id=%s", path, resp.status, _extract_request_id(payload))
        if resp.status >= 400:
            raise RuntimeError(f"GET {path} failed with status {resp.status}: {json.dumps(payload)}")
        return payload


async def _http_post(
    session: aiohttp.ClientSession,
    base: str,
    path: str,
    *,
    json_body: Dict[str, Any],
) -> Dict[str, Any]:
    url = f"{base.rstrip('/')}{path}"
    _LOGGER.info("POST %s body=%s", url, json.dumps(json_body))
    async with session.post(url, json=json_body) as resp:
        payload = await resp.json()
        _LOGGER.info("<- %s status=%s request_id=%s", path, resp.status, _extract_request_id(payload))
        if resp.status >= 400:
            raise RuntimeError(f"POST {path} failed with status {resp.status}: {json.dumps(payload)}")
        return payload


async def _http_delete(
    session: aiohttp.ClientSession,
    base: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    url = f"{base.rstrip('/')}{path}"
    _LOGGER.info("DELETE %s params=%s", url, params)
    async with session.delete(url, params=params) as resp:
        payload = await resp.json()
        _LOGGER.info("<- %s status=%s request_id=%s", path, resp.status, _extract_request_id(payload))
        if resp.status >= 400:
            raise RuntimeError(f"DELETE {path} failed with status {resp.status}: {json.dumps(payload)}")
        return payload


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Base URL of the running dex-proxy instance")
    parser.add_argument("--symbol", default="ETHUSDT", help="Binance symbol to source price data from (default: ETHUSDT)")
    parser.add_argument("--side", choices=["BUY", "SELL"], default="BUY", help="Order side (default: BUY)")
    parser.add_argument("--qty", type=Decimal, default=Decimal("0.001"), help="Base asset quantity to trade")
    parser.add_argument(
        "--price-offset-ticks",
        type=int,
        default=1,
        help="How many price ticks to step away from the top of book (default: 1)",
    )
    parser.add_argument("--instrument", help="Override Harbor instrument symbol if automatic mapping fails")
    parser.add_argument("--client-prefix", default="vasquez", help="Prefix for generated client order ids")
    parser.add_argument("--log-level", default="INFO", help="Python logging level (default: INFO)")
    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(message)s")

    base_symbol, quote_symbol = _split_symbol(args.symbol)
    _LOGGER.info("Resolved Binance symbol %s -> base=%s quote=%s", args.symbol, base_symbol, quote_symbol)

    async with aiohttp.ClientSession() as session:
        markets_payload = await _http_get(session, args.base, "/public/harbor/get_markets")
        market = _select_market(markets_payload, instrument=args.instrument, base=base_symbol, quote=quote_symbol)
        _LOGGER.info(
            "Selected Harbor instrument %s (base=%s quote=%s priceTick=%s qtyTick=%s)",
            market.instrument,
            market.base_symbol,
            market.quote_symbol,
            market.price_tick,
            market.qty_tick,
        )

        async with BinanceClient(session=session) as binance:
            book = await binance.fetch_book_ticker(args.symbol)
            best_bid = Decimal(book["bidPrice"])
            best_ask = Decimal(book["askPrice"])
            _LOGGER.info("Binance best bid=%s ask=%s", best_bid, best_ask)

        offset = Decimal(args.price_offset_ticks) * market.price_tick
        if args.side == "BUY":
            raw_price = best_bid - offset
        else:
            raw_price = best_ask + offset
        price = _align_price(raw_price, tick=market.price_tick, side=args.side)
        qty = _align_qty(args.qty, tick=market.qty_tick)
        _LOGGER.info("Tick-aligned price=%s qty=%s", price, qty)

        balances = await _http_get(session, args.base, "/public/harbor/get_balance")
        _LOGGER.info("Balances response: %s", json.dumps(balances, indent=2))

        client_order_id = f"{args.client_prefix}-{time.time_ns()}"
        insert_body = {
            "client_request_id": client_order_id,
            "instrument": market.instrument,
            "side": args.side,
            "order_type": "LIMIT",
            "base_ccy_symbol": market.base_symbol,
            "quote_ccy_symbol": market.quote_symbol,
            "price": format(price, "f"),
            "base_qty": format(qty, "f"),
        }
        insert_response = await _http_post(session, args.base, "/private/insert-order", json_body=insert_body)
        _LOGGER.info("Insert-order response: %s", json.dumps(insert_response, indent=2))

        open_orders = await _http_get(session, args.base, "/public/orders")
        _LOGGER.info("Open orders: %s", json.dumps(open_orders, indent=2))

        cancel_params = {"client_request_id": client_order_id}
        cancel_response = await _http_delete(session, args.base, "/private/cancel-request", params=cancel_params)
        _LOGGER.info("Cancel response: %s", json.dumps(cancel_response, indent=2))

        final_orders = await _http_get(session, args.base, "/public/orders")
        _LOGGER.info("Open orders after cancel: %s", json.dumps(final_orders, indent=2))

    _LOGGER.info("Workflow complete. client_order_id=%s send_timestamp_ns=%s", client_order_id, now_ns())
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
