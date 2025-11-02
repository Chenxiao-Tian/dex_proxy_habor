"""Minimal Harbor adapter demo script.

This script exercises the spec-aligned webserver endpoints provided by the Harbor
adapter by performing the following steps:

1. Approve a token allowance for trading
2. Insert a limit order
3. Poll the request status
4. Cancel the order

The adapter must be running locally with the configuration in
``harbor/harbor.config.json``. The script only prints responses for visibility
and does not assert on the payloads so it can be used against test or staging
environments without modification.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict

import aiohttp


BASE_URL = "http://localhost:1958"


async def _post(session: aiohttp.ClientSession, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    async with session.post(f"{BASE_URL}{path}", json=payload) as response:
        response.raise_for_status()
        return await response.json()


async def _delete(session: aiohttp.ClientSession, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    async with session.delete(f"{BASE_URL}{path}", params=params) as response:
        response.raise_for_status()
        return await response.json()


async def _get(session: aiohttp.ClientSession, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    async with session.get(f"{BASE_URL}{path}", params=params) as response:
        response.raise_for_status()
        return await response.json()


def _client_request_id(prefix: str) -> str:
    return f"demo-{prefix}-{int(time.time() * 1_000_000_000)}"


async def main() -> None:
    async with aiohttp.ClientSession() as session:
        approve_id = _client_request_id("approve")
        approve_payload = {
            "client_request_id": approve_id,
            "token_symbol": "USDC",
            "amount": "1000",
        }
        approve_resp = await _post(session, "/private/approve-token", approve_payload)
        print("approve-token", approve_resp)

        order_id = _client_request_id("order")
        order_payload = {
            "client_request_id": order_id,
            "instrument": "btc.btc-eth.usdt",
            "side": "BUY",
            "order_type": "LIMIT",
            "base_ccy_symbol": "BTC",
            "quote_ccy_symbol": "USDT",
            "price": "100",
            "base_qty": "0.01",
        }
        order_resp = await _post(session, "/private/insert-order", order_payload)
        print("insert-order", order_resp)

        status_resp = await _get(
            session,
            "/public/get-request-status",
            {"client_request_id": order_id},
        )
        print("get-request-status", status_resp)

        cancel_resp = await _delete(
            session,
            "/private/cancel-request",
            {"client_request_id": order_id},
        )
        print("cancel-request", cancel_resp)


if __name__ == "__main__":
    asyncio.run(main())
