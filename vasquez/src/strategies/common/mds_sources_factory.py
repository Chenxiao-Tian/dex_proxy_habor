from .md_sources.binance import Binance
from .md_sources.md_source_base import MDSource


class MDSFactory:
    @staticmethod
    def create(exchange: str) -> MDSource:
        exchange = "binance"
        if exchange == "binance":
            return Binance()

        raise NotImplementedError(f"Pricer for exchange {exchange} is not implemented.")
