import logging
import asyncio

from abc import ABC, abstractmethod


from .common.quoter import Quoter
from gateways.gateway_factory import GatewayFactory


class Strategy(ABC):
    def __init__(self, config: dict):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        self._gateway = GatewayFactory.create(config["gateway"], config)
        self.quoters = {
            quoter_index: self._create_quoter(quoter_index, quoter_config)
            for quoter_index, quoter_config in self.config["quoters"].items()
        }

    def _create_quoter(
        self,
        quoter_index,
        quoter_config,
    ) -> Quoter:
        return Quoter(quoter_index, quoter_config, self._gateway)

    @abstractmethod
    async def start(self):
        self.logger.info("Starting")

        # assets = set(
        #     [quoter.base_ccy for quoter in self.quoters.values()]
        #     + [quoter.quote_ccy for quoter in self.quoters.values()]
        # )

        for quoter in self.quoters.values():
            await quoter.start()
