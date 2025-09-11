import asyncio
import logging
from typing import Dict, Tuple, Awaitable, List

from eth_account.signers.local import LocalAccount
from eth_typing import ChecksumAddress
from hexbytes import HexBytes
from web3 import AsyncWeb3
from web3.types import TxParams, Nonce


#
# Initial implementation https://github.com/liquid-labs-inc/gte-python-sdk/blob/bcad6f887798e04f61c373f8cdf7c6732e9c906d/src/gte_py/api/chain/utils.py#L344
#
class Web3RequestManager:
    instances: Dict[ChecksumAddress, "Web3RequestManager"] = {}

    @classmethod
    async def ensure_instance(
            cls, web3: AsyncWeb3,
            account: LocalAccount
    ) -> "Web3RequestManager":
        """Ensure a singleton instance of Web3RequestManager for the given account address"""
        if account.address not in cls.instances:
            cls.instances[account.address] = Web3RequestManager(web3, account)
            await cls.instances[account.address].start()
        return cls.instances[account.address]
    
    @classmethod
    async def clear_instance(cls, account: LocalAccount):
        if account.address in cls.instances:
            await cls.instances[account.address].stop()
            del cls.instances[account.address]

    def __init__(self, web3: AsyncWeb3, account: LocalAccount):
        self.web3 = web3
        self.account = account
        self._tx_queue: asyncio.Queue[
            Tuple[TxParams | Awaitable[TxParams], asyncio.Future[HexBytes], asyncio.Future[None]]] = (
            asyncio.Queue()
        )
        self.free_nonces: List[Nonce] = []
        self._prev_latest_nonce: Nonce = Nonce(0)
        self.next_nonce: Nonce = Nonce(0)
        self.lock = asyncio.Lock()
        self.is_running = False
        self.confirmation_task = None
        self.logger = logging.getLogger(__name__)

    async def start(self):
        """Initialize and start processing"""
        await self.sync_nonce()
        self.is_running = True
        self.confirmation_task = asyncio.create_task(self._monitor_confirmations())

    async def stop(self):
        """Graceful shutdown"""
        self.is_running = False
        if self.confirmation_task:
            await self.confirmation_task

    async def sync_nonce(self):
        """Update nonce from blockchain state"""
        async with self.lock:
            self.logger.info('Trying to sync nonce')
            latest: Nonce = await self.web3.eth.get_transaction_count(
                self.account.address, block_identifier="latest"
            )
            pending: Nonce = await self.web3.eth.get_transaction_count(
                self.account.address, block_identifier="pending"
            )
            self.logger.info(f"Latest nonce: {latest - 1}, pending nonce: {pending - 1}, next nonce: {self.next_nonce}")
            # do not update from latest, as there could be blocked transactions already
            self.next_nonce = max(latest, self.next_nonce)
            nonce = latest
            if latest < pending and (nonce in self.free_nonces or latest == self._prev_latest_nonce):
                # nonce to be recycled
                # or
                # transactions stuck for 5 seconds
                self.logger.warning(
                    f"Nonce gap exists from {nonce} up to {self.next_nonce}"
                )
                try:
                    self.free_nonces.remove(nonce)
                except ValueError:
                    pass

            self._prev_latest_nonce = latest

    async def get_nonce(self):
        async with self.lock:
            if len(self.free_nonces) == 0:
                nonce = self.next_nonce
                self.logger.debug(f"Get nonce {nonce}")
                self.next_nonce += 1
            else:
                nonce = self.free_nonces.pop(0)
                self.logger.debug(f"Get nonce {nonce}")
            return nonce

    async def put_nonce(self, nonce):
        async with self.lock:
            self.logger.debug(f"Put nonce {nonce}")
            self.free_nonces.append(nonce)
            self.free_nonces.sort()

            while len(self.free_nonces) > 0:
                nonce = self.free_nonces[-1]
                if nonce + 1 == self.next_nonce:
                    self.logger.info(f"Recycling nonce {nonce}")
                    self.free_nonces.pop()
                    self.next_nonce = nonce
                else:
                    break

    async def _monitor_confirmations(self):
        """Dedicated confirmation monitoring task"""
        await asyncio.sleep(5)
        while self.is_running:
            await self.sync_nonce()
            await asyncio.sleep(5)
