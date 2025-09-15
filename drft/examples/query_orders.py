import asyncio

from .make_drift_client import *
from dex_proxy.utils import full_order_to_dict


async def main():
    api = await make_drift_client()

    orders = api.get_open_orders()
    if len(orders) == 0:
        print("there are no open orders")
        return

    for cnt, order in enumerate(orders):
        print(f"\norder {cnt}: {full_order_to_dict(order)}")


if __name__ == "__main__":
    asyncio.run(main())
    print("done")
