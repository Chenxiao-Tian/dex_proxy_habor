import asyncio

from .make_drift_client import *


async def main():
    api = await make_drift_client()

    orders = api.get_open_orders()
    if len(orders) == 0:
        print("there are no open orders")
        return

    print(f"there are {len(orders)} open orders")
    print("canceling all orders...")
    tx_sig = await api.conn.client.cancel_orders()
    print(f"cancel all orders tx_sig: {tx_sig}")


if __name__ == "__main__":
    asyncio.run(main())
    print("done")
