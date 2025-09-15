import asyncio

from .make_drift_client import *
from driftpy.types import (
    OrderType,
    OrderParams,
    PositionDirection,
    PostOnlyParams,
    MarketType,
)

AMMOUNT = 0.0001
PERP_MARKET_INDEX = 1  # BTC-PERP
PRICE = 72000
ORDER_ID = 13


async def main():
    api = await make_drift_client()

    perp_amount = api.conn.client.convert_to_perp_precision(AMMOUNT)
    print(f"perp amount: {AMMOUNT} {perp_amount}")
    perp_price = api.conn.client.convert_to_price_precision(PRICE)
    print(f"perp price:  {PRICE} {perp_price}")

    # place order to long (bid/buy) 1 SOL-PERP @ $174.99 (post only)
    order_params = OrderParams(
        market_type=MarketType.Perp(),
        order_type=OrderType.Limit(),
        base_asset_amount=perp_amount,
        market_index=PERP_MARKET_INDEX,
        direction=PositionDirection.Long(),
        price=perp_price,
        post_only=PostOnlyParams.TryPostOnly(),
        user_order_id=ORDER_ID,
    )
    tx_sig = await api.conn.client.place_perp_order(order_params)
    print(f"perp order tx_sig: {tx_sig}")


if __name__ == "__main__":
    asyncio.run(main())
    print("done")
