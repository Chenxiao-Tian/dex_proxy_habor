import asyncio
import logging
from typing import Dict, Optional

from pantheon import Pantheon
from .drift_connector import (
    DriftConfiguration,
    DriftConnector,
)

from solana.rpc.commitment import Processed

from driftpy.constants.config import DriftEnv
from driftpy.drift_client import DriftClient

# A pool of DriftClient => each will be using a different RPC node


class ClientsPool:

    def __init__(self, pantheon: Pantheon, config: dict, env: DriftEnv):
        self.__logger = logging.getLogger("CLIENTS_POOL")
        self.__pantheon = pantheon
        self.__config = config
        self.__env = env

        self.__drift_clients: Dict[str, DriftClient] = {}

        self.__leading_client: str = None
        self.__latest_seen_slot: int = 0
        self.__refresh_leading_client_interval_s = self.__config["refresh_leading_client_interval_s"]

    async def start(self, secret: list):
        assert (
            len(self.__config["urls"]) > 0
        ), "No solana RPC url provided in clients_pool"

        for src_name, url in self.__config["urls"].items():
            conn_config = DriftConfiguration(
                env=self.__env,
                url=url,
                public_key=self.__config["public_key"],
                subaccount=self.__config.get("subaccount", 0),
                skip_preflight=self.__config.get("skip_solana_preflight_checks", False),
                blockhash_refresh_interval_secs=self.__config.get(
                    "blockhash_refresh_interval_secs", 1
                ),
                compute_unit_limit=self.__config.get("compute_unit_limit"),
                compute_unit_price=self.__config.get("compute_unit_price"),
            )

            drift_connector = DriftConnector(config=conn_config)
            drift_connection = await drift_connector.get_connection(secret=secret)
            drift_client = drift_connection.client
            self.__drift_clients[src_name] = drift_client

            if self.__leading_client is None:
                self.__leading_client = src_name

        self.__pantheon.spawn(self.__track_leading_client())

    def get_all_clients(self) -> Dict[str, DriftClient]:
        return self.__drift_clients

    def get_leading_client_name(self) -> str:
        return self.__leading_client

    def get_client_by_name(self, client_name: str) -> DriftClient:
        return self.__drift_clients[client_name]

    def get_client(self) -> DriftClient:
        self.__logger.debug(f"Leading client is {self.__leading_client}")
        return self.__drift_clients[self.__leading_client]

    async def get_current_slot(self, drift_client: Optional[DriftClient] = None) -> Optional[int]:
        try:
            if drift_client is None:
                drift_client = self.get_client()

            return (await drift_client.connection.get_slot(commitment=Processed)).value
        except Exception as ex:
            self.__logger.exception("Error getting current slot %r", ex)

            return None

    async def __track_leading_client(self):
        while True:
            try:
                tasks = [
                    self.__update_leading_client(src_name)
                    for src_name in self.__drift_clients
                ]

                await asyncio.gather(*tasks)
            except Exception as ex:
                self.__logger.exception("Error while tracking leading client %r", ex)

            await self.__pantheon.sleep(self.__refresh_leading_client_interval_s)

    async def __update_leading_client(self, src_name: str):
        drift_client = self.__drift_clients[src_name]
        current_slot = await self.get_current_slot(drift_client=drift_client)

        if current_slot:
            self.__logger.debug(f"[{src_name}] Current slot is {current_slot}")

            if current_slot > self.__latest_seen_slot:
                self.__logger.debug(f"{src_name} is leading client now")
                self.__leading_client = src_name
                self.__latest_seen_slot = current_slot
        else:
            self.__logger.warning(f"[{src_name}] did not get current slot")
