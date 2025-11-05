import asyncio
import logging

from decimal import Decimal
from abc import ABC, abstractmethod

from pantheon import Pantheon

# from pantheon.message_client.message_client_factory import MessageClientFactory
# from pantheon.message_client.balance_message_client import (
#    BalanceUpdateStr,
#    BalanceStrStorageClient,
# )

from common.types import Ccy
from common.constants import ZERO

from gte_py.clients import Client as GteClient
from gte_py.configs import TESTNET_CONFIG
from web3 import AsyncWeb3
from eth_typing import ChecksumAddress


class BalanceProvider(ABC):
    def __init__(self, pantheon: Pantheon):
        self.pantheon = pantheon
        self.logger = logging.getLogger(self.__class__.__name__)
        self._balances: dict[Ccy, Decimal] = {}

    @abstractmethod
    async def start(self, ccy: list[Ccy]):
        pass

    @abstractmethod
    async def get_available_balance(self, ccy: Ccy) -> Decimal:
        pass


# class InternalBalanceProvider(BalanceProvider):
#    def __init__(self, pantheon: Pantheon, factory: MessageClientFactory):
#        self.pantheon = pantheon
#        self.message_client_factory = factory
#        self.logger = logging.getLogger(self.__class__.__name__)
#
#        self._bp_client: BalanceStrStorageClient | None = None
#        self._account = pantheon.config["balance_provider"]["account"]
#
#    async def start(self, ccy: list[Ccy]):
#        self._bp_client = (
#            await self.message_client_factory.create_balance_str_storage_client()
#        )
#        await self._bp_client.add_subscription(account=self._account)
#        await self._bp_client.start()
#
#    async def get_available_balance(self, ccy: Ccy) -> Decimal:
#        balance: BalanceUpdateStr = self._bp_client.get(self._account, ccy.value)
#
#        if balance is None:
#            self.logger.warning(f"{self._account}/{ccy}: no balance data")
#            return ZERO
#
#        if not balance.is_healthy:
#            self.logger.warning(f"{self._account}/{ccy}: balance is not healthy")
#            return ZERO
#
#        self.logger.info(f"{self._account}/{ccy}: {balance.available_margin} available")
#        return balance.available_margin


class GteBalanceProvider(BalanceProvider):
    def __init__(self, pantheon: Pantheon):
        super().__init__(pantheon)

        self._assets: dict[Ccy, ChecksumAddress] = {}
        self._address = AsyncWeb3.to_checksum_address(
            "0x03CdE1E0bc6C1e096505253b310Cf454b0b462FB"
        )

        self._w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(TESTNET_CONFIG.rpc_http))
        self._client = GteClient(
            web3=self._w3,
            config=TESTNET_CONFIG,
            sender_address=self._address,
        )

    async def start(self, ccy: list[Ccy]):
        await self._client.init()

        self._assets = {
            Ccy.ETH: AsyncWeb3.to_checksum_address(
                "0x776401b9bc8aae31a685731b7147d4445fd9fb19"
            ),
            Ccy.CUSD: AsyncWeb3.to_checksum_address(
                "0xE9b6e75C243B6100ffcb1c66e8f78F96FeeA727F"
            ),
        }

        self.pantheon.spawn(self._poll_balances())

    async def get_available_balance(self, ccy: Ccy) -> Decimal:
        return self._balances.get(ccy, Decimal(0))

    async def _poll_balances(self):
        while True:
            for ccy, address in self._assets.items():
                try:
                    _, balance = await self._client.execution.get_balance(
                        address, self._address
                    )
                    self.logger.info(f"{ccy.value} exchange balance: {balance}")
                    self._balances[ccy] = Decimal(balance)
                except Exception as e:
                    self.logger.error(
                        f"Error getting balance for {ccy.value}: {e}", exc_info=True
                    )
            await asyncio.sleep(2)


# More specific balance providers follow...
