import asyncio

from .make_drift_client import *
from driftpy.types import (
    OrderType,
    OrderParams,
    PositionDirection,
    PostOnlyParams,
    MarketType,
)

AMMOUNT = 0.1
SPOT_MARKET_INDEX = 1  # SOL
PRICE = 138.3
ORDER_ID = 42


async def main():
    api: DriftApi = await make_drift_client()

    spot_amount = api.conn.client.convert_to_spot_precision(AMMOUNT, SPOT_MARKET_INDEX)
    print(f"spot amount: {spot_amount}")
    spot_price = api.conn.client.convert_to_price_precision(PRICE)
    print(f"spot price:  {spot_price}")

    # place order to short (ask/sell) 0.1 SOL @ $138.3 (post only)
    order_params = OrderParams(
        market_type=MarketType.Spot(),
        order_type=OrderType.Limit(),
        base_asset_amount=spot_amount,
        market_index=SPOT_MARKET_INDEX,
        direction=PositionDirection.Short(),
        user_order_id=ORDER_ID,
        price=spot_price,
        post_only=PostOnlyParams.TryPostOnly()
    )
    tx_sig = await api.conn.client.place_spot_order(order_params)
    print(f"spot order tx_sig: {tx_sig}")


if __name__ == "__main__":
    asyncio.run(main())
    print("done")
