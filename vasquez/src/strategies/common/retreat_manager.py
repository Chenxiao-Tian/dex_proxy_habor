import logging
from decimal import Decimal

from common.types import Ccy
from common.constants import ZERO

from gateways.gateway import Gateway


class SpotBalanceRetreatManager:
    def __init__(self, gateway: Gateway):
        self.logger = logging.getLogger(f"{self.__class__.__name__}")
        self._gateway = gateway

        self.low_balance_threshold = Decimal("50000000")
        self.high_balance_threshold = Decimal("80000000")
        self.min_balance_threshold = Decimal("0")
        self.max_balance_threshold = Decimal("10000000000")

        self.low_balance_lean_bps = 5
        self.high_balance_lean_bps = 5
        self.exponent = 1

    async def get_adj_in_bps(self, ccy: Ccy) -> Decimal:
        total_balance = await self._gateway.get_available_balance(ccy)

        if self.low_balance_threshold <= total_balance <= self.high_balance_threshold:
            return ZERO

        if total_balance > self.high_balance_threshold:
            lean_sign = -1
            lean_bps = self.high_balance_lean_bps
            position_ratio = (total_balance - self.high_balance_threshold) / (
                self.max_balance_threshold - self.high_balance_threshold
            )
        else:
            lean_sign = 1
            lean_bps = self.low_balance_lean_bps
            position_ratio = (self.low_balance_threshold - total_balance) / (
                self.low_balance_threshold - self.min_balance_threshold
            )

        assert position_ratio >= 0
        adj_in_bps = (
            lean_sign
            * Decimal(pow(min(position_ratio, Decimal(1)), self.exponent))
            * lean_bps
        )
        return adj_in_bps
