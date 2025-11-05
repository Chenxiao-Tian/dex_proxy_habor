from typing import NewType
from enum import Enum

Account = NewType("Account", str)


class Ccy(Enum):
    MEOW = "MEOW"
    ETH = "ETH"
    WETH = "WETH"
    BTC = "BTC"
    GBTC = "gBTC"
    USD = "USD"
    USDC = "USDC"
    CUSD = "cUSD"
    USDT = "USDT"
    SOL = "SOL"

    def __str__(self):
        return f"{self.value}"
