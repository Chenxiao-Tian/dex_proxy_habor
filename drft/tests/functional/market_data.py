from typing import Optional

import aiohttp
from driftpy.constants import PRICE_PRECISION

from order_generator import OrderGenerator


class MarketData:
    DRIFT_TEST_ACCOUNT: str = "drift_test_0"

    def __init__(self, order_generator: OrderGenerator):
        self.order_generator = order_generator

    async def _get_l2(self, url: str, total_timeout: float):
        timeout = aiohttp.ClientTimeout(total=total_timeout)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                return await response.json(content_type=None)

    async def get_price_for_gtc_order(self, symbol: str, side: Optional[str] = "SELL"):
        # symbol: SOL-PERP
        l2 = await self._get_l2(
            f"https://dlob.drift.trade/l2?marketName={symbol}&depth=10&includeOracle=true&includeVamm=true", 10
        )
        assert l2 is not None

        if side == "SELL":
            # multiply the highest price so the order will be outside of the market
            high_price = float(l2['asks'][-1]['price']) * 2 / PRICE_PRECISION
            return high_price
        elif side == "BUY":
            low_price = float(l2['bids'][-1]['price']) / 2 / PRICE_PRECISION
            return low_price
        else:
            raise ValueError(f"Invalid side: {side}")

    async def get_price_for_ioc_order(self, symbol: str, side: Optional[str] = "SELL"):
        l2 = await self._get_l2(
            f"https://dlob.drift.trade/l2?marketName={symbol}&depth=50&includeOracle=true&includeVamm=true", 10
        )
        assert l2 is not None

        if side == "SELL":
            # make price a bit cheaper to be sure it will be immediately traded
            ioc_price = (float(l2['bids'][-1]['price']) * 0.98) / PRICE_PRECISION
            return ioc_price
        elif side == "BUY":
            # make price a bit higher to be sure it will be immediately traded
            ioc_price = (float(l2['asks'][-1]['price']) * 1.02) / PRICE_PRECISION
            return ioc_price

    async def get_ioc_order_data(self, client_order_id: Optional[str] = None, symbol: Optional[str] = "SOL-PERP",
                                 side: Optional[str] = "SELL", account: Optional[str] = DRIFT_TEST_ACCOUNT):
        ioc_price = await self.get_price_for_ioc_order(symbol, side)

        return self.order_generator.generate_ioc_order_data(account, client_order_id, ioc_price, symbol, side)

    async def get_gtc_order_data(self, client_order_id: Optional[str] = None, symbol: Optional[str] = "SOL-PERP",
                                 side: Optional[str] = "SELL", account: Optional[str] = DRIFT_TEST_ACCOUNT):
        high_price = await self.get_price_for_gtc_order(symbol, side)

        return self.order_generator.generate_gtc_order_data(account, client_order_id, high_price, symbol, side)
