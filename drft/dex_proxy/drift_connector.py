import dataclasses
import logging
from typing import cast, Literal, Optional

from anchorpy import Wallet
from anchorpy.program.core import Program
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Commitment, Confirmed
from solana.rpc.types import TxOpts
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from driftpy.constants.config import DriftEnv, DRIFT_PROGRAM_ID
from driftpy.drift_client import DriftClient, DEFAULT_TX_OPTIONS
from driftpy.events.event_subscriber import EventSubscriber
from driftpy.events.types import (
    PollingLogProviderConfig,
    WebsocketLogProviderConfig,
    EventSubscriptionOptions,
    EventType,
    DEFAULT_EVENT_TYPES,
)
from driftpy.types import TxParams
from driftpy.tx.fast_tx_sender import FastTxSender


@dataclasses.dataclass
class DriftConfiguration:
    env: DriftEnv
    url: str
    public_key: str = None
    sub_account_ids: list | None = None
    skip_preflight: bool = False
    blockhash_refresh_interval_secs: int = 1
    compute_unit_limit: int = None
    compute_unit_price: int = None


class DriftConnection:
    def __init__(self, config: DriftConfiguration, secret: Optional[list]=None):
        assert config.env in ["mainnet", "devnet"], f"invalid env: {config.env}"

        authority = Pubkey.from_string(config.public_key)

        if secret:
            wallet = Wallet(Keypair.from_bytes(secret))
            assert authority == wallet.public_key, (
                f"Mismatch in expected public key {authority} and "
                f"public key generated from secret {wallet.public_key}"
            )
        else:
            wallet = Wallet.dummy()

        self.__logger = logging.getLogger("drift_connector")
        self.__logger.debug(f"Setup Wallet with public key: {wallet.public_key}")

        opts_dict = {
            name: value for name, value in DEFAULT_TX_OPTIONS._asdict().items()
        }
        opts_dict["skip_preflight"] = config.skip_preflight
        opts = TxOpts(**opts_dict)

        env = cast(DriftEnv, config.env)
        self.connection = AsyncClient(endpoint=config.url, timeout=120)

        tx_params = TxParams(
            compute_units=config.compute_unit_limit,
            compute_units_price=config.compute_unit_price,
        )

        tx_sender = FastTxSender(
            connection=self.connection,
            opts=opts,
            blockhash_refresh_interval_secs=config.blockhash_refresh_interval_secs,
            blockhash_commitment=Confirmed,
        )

        self.client = DriftClient(
            connection=self.connection,
            wallet=wallet,
            env=env,
            opts=opts,
            authority=authority,
            tx_params=tx_params,
            tx_sender=tx_sender,
            sub_account_ids=config.sub_account_ids
        )
        self.pantheon = None

    async def start(self):
        await self.client.subscribe()

    async def get_current_slot(self, commitment: Optional[Commitment] = Confirmed):
        return (await self.connection.get_slot(commitment=commitment)).value

    def show_user_info(self):
        user_account = self.client.get_user_account()
        user_stats = self.client.get_user_stats()
        self.__logger.debug(f"User Referrer Info: {user_stats.get_referrer_info()}")
        self.__logger.debug(f"User Address: {user_account.authority}")
        self.__logger.debug(
            f"UserAccount Solana Program: {self.client.get_user_account_public_key()}, subaccount_id: {user_account.sub_account_id}"
        )


class DriftSubscriber:

    def __init__(
        self,
        config: DriftConfiguration,
        type: Literal["polling", "websocket"] = "websocket",
        connection: Optional[AsyncClient] = None,
        program: Optional[Program] = None,
    ):
        self.callbacks = []
        self.event_subscriber: Optional[EventSubscriber] = None
        self.connection = connection or AsyncClient(config.url)
        self.program = (
            program or DriftClient(self.connection, Wallet.dummy(), config.env).program
        )

        if type == "polling":
            self.log_provider_config = PollingLogProviderConfig()
        elif type == "websocket":
            self.log_provider_config = WebsocketLogProviderConfig()
        else:
            raise ValueError("Invalid type")

    def add_callback(self, callback):
        self.callbacks.append(callback)
        if self.event_subscriber:
            self.event_subscriber.event_emitter.new_event += callback

    async def start(
        self,
        address: Pubkey = DRIFT_PROGRAM_ID,
        event_types: tuple[EventType] = DEFAULT_EVENT_TYPES,
        commitment: Commitment = Confirmed,
    ):
        options = EventSubscriptionOptions(
            address=address,
            event_types=event_types,
            max_tx=4096,
            max_events_per_type=4096,
            order_by="blockchain",
            order_dir="asc",
            commitment=commitment,
            log_provider_config=self.log_provider_config,
        )

        self.event_subscriber = EventSubscriber(self.connection, self.program, options)
        self.event_subscriber.subscribe()
        for callback in self.callbacks:
            self.event_subscriber.event_emitter.new_event += callback


class DriftConnector:
    def __init__(self, config: DriftConfiguration):
        self.config = config

    async def get_connection(self, secret: list) -> DriftConnection:
        conn = DriftConnection(config=self.config, secret=secret)
        await conn.start()
        return conn

    async def get_subscriber(
        self,
        address: Pubkey = DRIFT_PROGRAM_ID,
        event_types: tuple[EventType] = DEFAULT_EVENT_TYPES,
        commitment: Commitment = Confirmed,
        connection: AsyncClient = None,
        program: Program = None,
    ) -> DriftSubscriber:
        subscriber = DriftSubscriber(
            config=self.config, connection=connection, program=program
        )
        await subscriber.start(
            address=address, event_types=event_types, commitment=commitment
        )
        return subscriber
