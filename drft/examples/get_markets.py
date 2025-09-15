import asyncio

from .make_drift_client import *


async def get_accounts(drift_client: DriftApi, market: str):
    all_markets = await drift_client.force_get_markets(market)
    print(f"{market}: {all_markets}")


async def main():
    drift_client = await make_drift_client()

    await get_accounts(drift_client, "PerpMarket")
    await get_accounts(drift_client, "SpotMarket")


if __name__ == "__main__":
    asyncio.run(main())
    print("done")
