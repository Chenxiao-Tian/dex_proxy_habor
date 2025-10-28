"""Simple script that places and cancels a Harbor order using the REST client."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from decimal import Decimal

from harbor.dex_proxy.client import HarborRESTClient
from harbor.dex_proxy.exceptions import HarborAPIError
from harbor.dex_proxy.utils import ensure_multiple


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True, help="Harbor market symbol, e.g. btc.btc-eth.usdt")
    parser.add_argument("--price", required=True, type=Decimal, help="Order price respecting priceTick")
    parser.add_argument("--quantity", required=True, type=Decimal, help="Order quantity respecting qtyTick")
    parser.add_argument("--side", default="BUY", choices=["BUY", "SELL"], help="Order side")
    parser.add_argument("--order-type", default="LIMIT", help="Order type (default: LIMIT)")
    parser.add_argument("--time-in-force", default="gtc", help="Time in force (default: gtc)")
    parser.add_argument("--client-order-id", default="demo-harbor-order", help="Client order identifier")
    args = parser.parse_args()

    api_key = os.environ.get("HARBOR_API_KEY")
    if not api_key:
        print("HARBOR_API_KEY environment variable is required", file=sys.stderr)
        return 2

    client = HarborRESTClient(base_url="https://api.harbor-dev.xyz/api/v1", api_key=api_key)

    try:
        markets = await client.get_markets()
        symbol_info = next((m for m in markets if m["symbol"] == args.symbol), None)
        if not symbol_info:
            print(f"Symbol {args.symbol} not found in /markets", file=sys.stderr)
            return 3

        price = ensure_multiple(args.price, Decimal(symbol_info["priceTick"]), field_name="price")
        quantity = ensure_multiple(args.quantity, Decimal(symbol_info["qtyTick"]), field_name="quantity")

        order_payload = {
            "symbol": args.symbol,
            "clientOrderId": args.client_order_id,
            "type": args.order_type.lower(),
            "side": args.side.lower(),
            "price": format(price, "f"),
            "qty": format(quantity, "f"),
            "timeInForce": args.time_in_force,
        }

        print("Creating order:")
        print(order_payload)
        create_response = await client.create_order(order_payload)
        print("Create response:")
        print(create_response)

        print("Cancelling order:")
        cancel_response = await client.cancel_order(client_order_id=args.client_order_id)
        print(cancel_response)

    except HarborAPIError as exc:
        print(str(exc), file=sys.stderr)
        if exc.payload:
            print(exc.payload, file=sys.stderr)
        return 1
    finally:
        await client.close()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
