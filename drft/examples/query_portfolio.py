import asyncio

from .make_drift_client import *


async def main():
    api = await make_drift_client()

    for position in api.get_spot_positions().items():
        print(position)
    for position in api.get_perp_positions().items():
        print(position)


if __name__ == "__main__":
    asyncio.run(main())
    print("done")
