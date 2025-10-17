import aiohttp
import logging
from decimal import Decimal
from typing import Dict

from drift_api import MarketType
from clients_pool import ClientsPool

from solders.pubkey import Pubkey
from solana.rpc.commitment import Confirmed

from driftpy.addresses import get_user_stats_account_public_key
from driftpy.user_map.user_map import UserMap
from driftpy.user_map.user_map_config import UserMapConfig, WebsocketConfig
from driftpy.types import MakerInfo, PositionDirection, market_type_to_string

class UserMaps:
    def __init__(self):
        self.__user_maps: Dict[str, UserMap] = {}

    async def start(self, clients_pool: ClientsPool):
        websocket_config = WebsocketConfig(commitment=Confirmed, resub_timeout_ms=1000)
        for drift_client_name, drift_client in clients_pool.get_all_clients().items():
            self.__user_maps[drift_client_name] = UserMap(
                UserMapConfig(
                    drift_client=drift_client,
                    subscription_config=websocket_config,
                    connection=drift_client.connection,
                    skip_initial_load=True,
                    include_idle=False,
                )
            )
            await self.__user_maps[drift_client_name].subscribe()

    async def get_maker_user(self, drift_client_name, maker):
        return await self.__user_maps[drift_client_name].must_get(maker)

class Makers:
    def __init__(self, config: dict):
        self._logger = logging.getLogger("MAKERS")
        self._url = config["url"]
        self._request_timeout_s = config.get("request_timeout_s", 5)
        self._max_number_of_makers = config["max_number_of_makers"]
        self._user_maps = UserMaps()

    async def start(self, clients_pool: ClientsPool):
        await self._user_maps.start(clients_pool)

    async def get_makers(self,
                         drift_client_name: str,
                         program_id: int,
                         market_type: MarketType,
                         market_index: int,
                         direction: PositionDirection,
                         price_mult: int,
                         qty_mult: int):
        url = (f"{self._url}"
               f"?marketType={market_type_to_string(market_type)}"
               f"&marketIndex={market_index}")

        try:
            l3 = await self._get_l3(url)
        except Exception as ex:
            self._logger.exception(f"failed to get l3 for {url}: {ex}")
            return []

        book_side_to_take = ("asks" if direction == PositionDirection.Long()
                             else "bids")
        try:
            book_side = l3[book_side_to_take]
        except Exception as ex:
            self._logger.exception(f"failed to get book {book_side_to_take} "
                                   f"for {url}: {ex}")
            return []

        makers = []
        to_info = []
        num_makers = min(self._max_number_of_makers, len(book_side))
        try:
            for level in book_side[:num_makers]:
                price = Decimal(level["price"]) / price_mult
                qty = Decimal(level["size"]) / qty_mult
                maker = level["maker"]
                maker_public_key = Pubkey.from_string(maker)
                maker_user = await self._user_maps.get_maker_user(
                    drift_client_name=drift_client_name,
                    maker=maker,
                )
                maker_user_account = maker_user.get_user_account()
                makers.append(
                    MakerInfo(
                        maker=maker_public_key,
                        maker_stats=get_user_stats_account_public_key(
                            program_id=program_id,
                            authority=maker_user_account.authority,
                        ),
                        maker_user_account=maker_user_account,
                        order=None,
                    )
                )
                to_info.append(f"{maker}: {qty}@{price}")
            self._logger.info(f"got makers for {url}: {to_info}")
            return makers

        except Exception as ex:
            self._logger.exception(f"failed to get makers for {url}: {ex}")
            return []

    async def _get_l3(self, url: str):
        timeout = aiohttp.ClientTimeout(total=self._request_timeout_s)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                return await response.json(content_type=None)
