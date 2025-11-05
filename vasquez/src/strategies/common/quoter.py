import asyncio
import logging
from decimal import Decimal


from common.constants import NaN, ZERO
from common.utils import get_base_and_quote

from gateways.gateway import Gateway
from .bbo_pricer import BboPricer
from ..common.pricing_model.mid_price import MidPriceModel
from ..common.mds_sources_factory import MDSFactory
from .retreat_manager import SpotBalanceRetreatManager


class QuoteDecision:
    def __init__(
        self,
        bid_px: Decimal,
        bid_sz: Decimal,
        bid_sz_reason: str,
        ask_px: Decimal,
        ask_sz: Decimal,
        ask_sz_reason: str,
    ):
        self.bid_px = bid_px
        self.bid_sz = bid_sz
        self.bid_sz_reason = bid_sz_reason
        self.ask_px = ask_px
        self.ask_sz = ask_sz
        self.ask_sz_reason = ask_sz_reason

    def __eq__(self, other):
        return (
            self.bid_px == other.bid_px
            and self.ask_px == other.ask_px
            and self.bid_sz == other.bid_sz
            and self.ask_sz == other.ask_sz
        )

    def __str__(self):
        template = "<QD> {}> {} | {} <{} / sz reasons = ( {} | {} )"
        return template.format(
            self.bid_sz,
            self.bid_px,
            self.ask_px,
            self.ask_sz,
            self.bid_sz_reason,
            self.ask_sz_reason,
        )

    @staticmethod
    def empty(reason=None):
        return QuoteDecision(
            bid_px=NaN,
            bid_sz=ZERO,
            bid_sz_reason=reason,
            ask_px=NaN,
            ask_sz=ZERO,
            ask_sz_reason=reason,
        )


class Quoter:
    def __init__(
        self,
        quoter_index: str,
        config: dict,
        gateway: Gateway,
    ):
        self.logger = logging.getLogger(self.__class__.__name__)
        self._gateway = gateway
        self.tick_size = config.get("tick_size")

        # self.iid = get_iid_from_index(self.index)
        self.base_ccy, self.quote_ccy = get_base_and_quote(quoter_index.split("=")[0])
        self.ref_px = config.get("ref_price")
        self.base_ref_px = config.get("base_ref_price")
        self.quote_ref_px = config.get("quote_ref_price")
        self.quote_order_value = config.get("quote_order_value")
        self.tick_size = config.get("tick_size", 1)
        self.lot_size = config.get("lot_size", 1)
        self.min_balance_threshold = config.get("min_balance_threshold")
        self.max_balance_threshold = config.get("max_balance_threshold")

        self.exchange = config.get("ref_exchange")

        self.instrument = quoter_index

        self.allow_quoting = False

        self.price_queue = asyncio.Queue()
        self._pricer = BboPricer(
            self.price_queue,
            price_model=MidPriceModel(),
            mds_source=MDSFactory().create(self.exchange),
        )
        self.config = config
        self._retreat_manager = SpotBalanceRetreatManager(gateway)

    async def start(self):
        self.logger.info(f"[{self.instrument}] starting")

        self.allow_quoting = True

        asyncio.create_task(self._gateway.start())
        asyncio.create_task(self._run())

    async def _run(self):
        while True:
            try:
                total_balance = await self._gateway.get_available_balance(self.base_ccy)

                self.logger.debug(
                    f"{self.instrument} total balance=${total_balance:,.2f}, "
                )
            except Exception as e:
                self.logger.error(
                    f"Error updating total balance: {str(e)}", exc_info=True
                )

            await asyncio.sleep(5)

    async def get_decision(self) -> QuoteDecision:
        if not self.allow_quoting:
            return QuoteDecision.empty("Quoter is disabled")

        try:
            self.logger.info(f"quoting on instrument {self.instrument}")
            price_decision = await self._pricer.get_decision(self.config["cbs"])
            self.logger.info(f"[{self.instrument}] {price_decision}")
        except Exception as e:
            return QuoteDecision.empty(f"No price decision: {str(e)}")

        if price_decision.bid.is_nan() or price_decision.ask.is_nan():
            return QuoteDecision.empty("Bid/Ask price decision is nan")

        bid_px = price_decision.bid / self.quote_ref_px
        bid_px = bid_px.quantize(Decimal(str(self.tick_size)))
        ask_px = price_decision.ask / self.quote_ref_px
        ask_px = ask_px.quantize(Decimal(str(self.tick_size)))

        raw_bid_sz = self.quote_order_value / self.ref_px
        raw_ask_sz = self.quote_order_value / self.ref_px

        bid_sz, bid_sz_reason, ask_sz, ask_sz_reason = await self._decorate_order_size(
            raw_bid_sz,
            raw_ask_sz,
        )
        bid_sz = bid_sz.quantize(Decimal(str(self.lot_size)))
        ask_sz = ask_sz.quantize(Decimal(str(self.lot_size)))
        qd = QuoteDecision(
            bid_px=bid_px,
            bid_sz=bid_sz,
            bid_sz_reason=bid_sz_reason,
            ask_px=ask_px,
            ask_sz=ask_sz,
            ask_sz_reason=ask_sz_reason,
        )

        self.logger.info(
            f"[{self.instrument}] {qd} (spread={round(((qd.ask_px / qd.bid_px) - 1) * 10000, 1)} bps) "
            f"[fair_bid={round(bid_px, 8)}, fair_ask={round(ask_px, 8)}, "
        )

        return qd

    async def _decorate_order_size(
        self,
        raw_bid_sz: Decimal,
        raw_ask_sz: Decimal,
    ):
        total_balance = await self._gateway.get_available_balance(self.base_ccy)
        bid_sz_reason = None
        ask_sz_reason = None

        if total_balance >= self.max_balance_threshold:
            bid_sz = ZERO
            bid_sz_reason = (
                f"total balance {total_balance} exceeded "
                f"max balance threshold {self._retreat_manager.max_balance_threshold}"
            )
        else:
            # Cap quoted volume to not quote bigger than what would make you breach max balance threshold
            bid_sz = min(
                raw_bid_sz,
                (self.max_balance_threshold - total_balance),
            )

        if total_balance < self.min_balance_threshold - 100:
            ask_sz = ZERO
            ask_sz_reason = (
                f"total balance {total_balance} went below"
                f" min balance threshold {self.min_balance_threshold}"
            )
        else:
            # Cap quoted volume to not quote bigger than what would make you breach min balance threshold
            ask_sz = min(
                raw_ask_sz,
                (total_balance - self.min_balance_threshold),
            )

        return Decimal(bid_sz), bid_sz_reason, Decimal(ask_sz), ask_sz_reason
