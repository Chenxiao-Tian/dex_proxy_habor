import asyncio
from decimal import Decimal
from datetime import datetime
from common.constants import NaN, ZERO

from .md_sources.md_source_base import MDSource
from .pricing_model.price_model import PriceModel


class PriceDecision:
    __slots__ = ["bid", "ask", "timestamp", "details"]

    def __init__(self, bid: Decimal, ask: Decimal, details):
        self.bid = bid
        self.ask = ask
        self.timestamp = datetime.now()
        self.details = details

    @staticmethod
    def empty(details):
        return PriceDecision(NaN, NaN, details)

    def __eq__(self, other):
        # Treat them as different if it is longer than 5s
        if (abs(other.timestamp() - self.timestamp()) * 1_000_000_000) >= 5000000000:
            return False

        return self.bid == other.bid and self.ask == other.ask

    def __str__(self):
        return f"PriceDecision: {round(self.bid, 8)} | {round(self.ask, 8)} / details = {self.details}"


class BboPricer:
    def __init__(self, price_queue, mds_source: MDSource, price_model: PriceModel):
        self._price_queue = price_queue
        self._mds_source = mds_source
        self._pricing_model = price_model

    async def get_decision(self, instrument):
        try:
            price_details = self._mds_source.get_book(instrument)
            instrument_fair_price = self._pricing_model.compute(price_details)
            return PriceDecision(
                bid=Decimal(str(instrument_fair_price)),
                ask=Decimal(str(instrument_fair_price)),
                details=None,
            )
        except Exception as e:
            self.logger.error(f"Error getting book update: %r", e)

    #TODO(Mayank): Remove this unused code
    # async def _get_md_subscription(
    #     self, iid: InstrumentId, max_levels
    # ) -> MarketDataSubscription:
    #     connection = await self.md_provider.connect_market_data(iid.exchange)
    #     subscription = await connection.subscribe(
    #         iid.symbol,
    #     )
    #     return subscription

    # async def _listen_to_book_updates(
    #     self, iid: InstrumentId, md_subscription: MarketDataSubscription
    # ):
    #     while True:
    #         try:
    #             depth = await md_subscription.get_price_depth()
    #             await self._process_book_update(iid, depth)
    #         except Exception as e:
    #             self.logger.error(f"Error getting book update: %r", e)

    # async def _process_book_update(self, iid: InstrumentId, depth: PriceDepth):
    #     if len(depth.bids) == 0 or len(depth.asks) == 0:
    #         self.logger.error(f"Dropping {iid} from pricing model: invalid book")
    #         self._last_bids.pop(iid, None)
    #         self._last_asks.pop(iid, None)
    #         await self._recompute_mid()
    #         return

    #     price_normalizer = self._components[iid].price_normalizer
    #     ref_px = self._rpp.try_get_reference_price(price_normalizer.symbol)
    #     if ref_px.is_nan():
    #         # TODO: Should we stop trading here? I wonder if we will mistrade if this happens for a long time..
    #         self.logger.error(
    #             f"Dropping {iid} from pricing model: ref price {price_normalizer.symbol} is nan"
    #         )
    #         self._last_bids.pop(iid, None)
    #         self._last_asks.pop(iid, None)
    #         await self._recompute_mid()
    #         return

    #     bid = DepthLevel(depth.bids[0].price * ref_px, depth.bids[0].volume)
    #     ask = DepthLevel(depth.asks[0].price * ref_px, depth.asks[0].volume)

    #     self._last_bids[iid] = bid
    #     self._last_asks[iid] = ask

    #     await self._recompute_mid()

    # async def _recompute_mid(self):
    #     bids = list(self._last_bids.values())
    #     asks = list(self._last_asks.values())
    #     bids = sorted(bids, key=lambda x: x.price, reverse=True)
    #     asks = sorted(asks, key=lambda x: x.price)

    #     # net price and qty until bid < ask
    #     bid_index, ask_index = 0, 0
    #     while bid_index < len(bids) and ask_index < len(asks):
    #         bid = bids[bid_index]
    #         ask = asks[ask_index]
    #         if bid.price < ask.price:
    #             self._last_normalized_mid_px = (
    #                 bids[bid_index].price + asks[ask_index].price
    #             ) / 2
    #             await self._price_queue.put(self._last_normalized_mid_px)
    #             return

    #         self.logger.debug(f"In cross: {bid} | {ask}")
    #         if bid.volume > ask.volume:
    #             bid.volume -= ask.volume
    #             # ask level is drained, move to next ask level
    #             ask_index += 1
    #         elif bid.volume < ask.volume:
    #             # bid level is drained, move to next bid level
    #             ask.volume -= bid.volume
    #             bid_index += 1
    #         else:
    #             # bid and ask level cancel out, move both to next level
    #             bid_index += 1
    #             ask_index += 1

    #     self.logger.warning("Cannot uncross the book")
    #     self._last_normalized_mid_px = NaN

    # def get_fair(self) -> Decimal:
    #     # return Decimal(random.uniform(1.49, 1.51))
    #     if self._normalizer:
    #         # convert ETH/USD to WETH/USD with WETH/ETH normalizer
    #         ref_px = self._rpp.try_get_reference_price(self._normalizer.symbol)
    #         if ref_px.is_nan():
    #             return NaN
    #         return self._last_normalized_mid_px * ref_px
    #     else:
    #         return self._last_normalized_mid_px

    # async def start(self):
    #     self.logger.info(f"[{self.index}] Starting pricing models")
    #     await self._pricing_model.start()

    # def set_base_bracket_spread_in_bps(self, bracket_spread_in_bps: Decimal):
    #     if bracket_spread_in_bps >= Decimal("1"):
    #         self._half_spread = bracket_spread_in_bps / 10000

    # def get_base_bracket_spread_in_bps(self) -> int:
    #     assert self._half_spread > 0
    #     return int(self._half_spread * 10000)

    # def set_max_bracket_spread_in_bps(self, max_bracket_spread_in_bps: Decimal):
    #     if max_bracket_spread_in_bps >= Decimal("3"):
    #         self._max_spread = max_bracket_spread_in_bps / 10000

    # def set_min_bracket_spread_in_bps(self, min_bracket_spread_in_bps: Decimal):
    #     self._min_spread = min_bracket_spread_in_bps / 10000

    # def set_manual_skew_in_bps(self, manual_skew_in_bps: Decimal):
    #     self._manual_skew = manual_skew_in_bps / 10000

    # async def get_decision(self, base_ccy: Ccy) -> PriceDecision:
    #     fair = self._pricing_model.get_fair()
    #     fair_details = (self._pricing_model.name, self._pricing_model.weight, fair)

    #     if fair.is_nan():
    #         return PriceDecision.empty(fair_details)

    #     if self._half_spread is None:
    #         return PriceDecision.empty("half spread not yet ready")
    #     if self._manual_skew is None:
    #         return PriceDecision.empty("manual skew not yet ready")
    #     if self._max_spread is None:
    #         return PriceDecision.empty("max spread not yet ready")
    #     if self._min_spread is None:
    #         return PriceDecision.empty("min spread not yet ready")

    #     adj_in_bps = await self._retreat_manager.get_adj_in_bps(base_ccy)
    #     # if adj_in_bps is positive, shift quotes up towards agressive buy
    #     # if it's negative, shift quotes down towards aggressive sell
    #     bid_adj = -adj_in_bps / 10000
    #     ask_adj = adj_in_bps / 10000

    #     raw_bid_spread = self._half_spread + self._manual_skew + bid_adj
    #     self.logger.info(
    #         f"[{self.index}] rawBidSpread {round(raw_bid_spread, 5)} = "
    #         f"halfSpread {self._half_spread} + manualSkew {self._manual_skew} + bidAdj {round(bid_adj, 5)}"
    #     )

    #     raw_ask_spread = self._half_spread + self._manual_skew + ask_adj
    #     self.logger.info(
    #         f"[{self.index}] rawAskSpread {round(raw_ask_spread, 5)} = "
    #         f"halfSpread {self._half_spread} + manualSkew {self._manual_skew} + askAdj {round(ask_adj, 5)}"
    #     )

    #     bid_spread = min(max(raw_bid_spread, self._min_spread), self._max_spread)
    #     bid = fair * (1 - bid_spread)

    #     ask_spread = min(max(raw_ask_spread, self._min_spread), self._max_spread)
    #     ask = fair * (1 + ask_spread)

    #     return PriceDecision(bid=bid, ask=ask, details=fair_details)
