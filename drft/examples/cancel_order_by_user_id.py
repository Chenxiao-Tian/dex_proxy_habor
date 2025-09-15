import asyncio

from .make_drift_client import *


async def main():
    api = await make_drift_client()

    orders = api.get_open_orders()
    if len(orders) == 0:
        print("there are no open orders")
        return

    print(f"there are {len(orders)} open orders")
    order = orders[0]
    print(f"canceling order with client_order_id={order.drift_user_order_id}")
    tx_sig = await api.conn.client.cancel_order_by_user_id(order.drift_user_order_id)
    print(f"cancel order tx_sig: {tx_sig}")


if __name__ == "__main__":
    asyncio.run(main())
    print("done")
