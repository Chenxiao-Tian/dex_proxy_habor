import asyncio
import logging

from collections import defaultdict
from typing import Tuple
from web3 import Web3

from pantheon import Pantheon

from pyutils.exchange_apis import ApiFactory
from pyutils.exchange_apis.fireblocks_api import FireblocksApi
from pyutils.exchange_connectors import ConnectorFactory, ConnectorType


class WhitelistingManager:
    def __init__(self, pantheon: Pantheon, dex, config: dict):
        self.__pantheon = pantheon
        self.__dex = dex
        self.__config: dict = config["fireblocks"]

        self.__logger = logging.getLogger("whitelisting_manager")
        self.__first_value_fetched = asyncio.Event()

        api_factory = ApiFactory(ConnectorFactory(config.get("connectors")))
        self.__fireblocks_api: FireblocksApi = api_factory.create(self.__pantheon, ConnectorType.Fireblocks)

    async def start(self):
        self.__pantheon.spawn(self.__get_whitelisted_withdrawal_addresses_and_tokens_from_fireblocks())
        await self.__first_value_fetched.wait()

    async def __get_supported_tokens_from_fireblocks(self) -> Tuple[dict, dict]:
        # dict of : token_symbol -> (fireblocks_token_id, token_address)
        tokens_from_fireblocks = {}

        # dict of : fireblocks_token_id -> token_symbol
        supported_tokens_id = {}

        response = await self.__fireblocks_api.get_supported_assets()
        self.__logger.info(f"Fireblocks supported assets response: {response}")
        # Sample Response:
        #   [
        #       {
        #       "id": "FLIP_ETH_3G7F",
        #       "name": "Chainflip",
        #       "type": "ERC20",
        #       "contractAddress": "0x826180541412D574cf1336d22c0C0a287822678A",
        #       "nativeAsset": "ETH",
        #       "decimals": 18
        #       },
        #       {
        #       "id": "WETH",
        #       "name": "Wrapped Ether",
        #       "type": "ERC20",
        #       "contractAddress": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        #       "nativeAsset": "ETH",
        #       "decimals": 18
        #       }
        #   ]

        seen_tokens = set()
        for token in response:
            try:
                if (token["nativeAsset"] == self.__config["native_asset"]) and (token["type"] in self.__config["token_types"]):
                    temp = str(token["id"]).split("_")[0]
                    # remove all non-alphabetic characters to get symbol
                    symbol = "".join([ch for ch in temp if ch.isalpha()])

                    if len(symbol) == 0:
                        continue

                    if symbol in seen_tokens:
                        # Two or more tokens may have same computed symbol
                        # e.g:
                        # [
                        #   { "id": "1INCH", "name": "1INCH Token", "type": "ERC20", "contractAddress": "0x111111111117dC0aa78b770fA6A738034120C302", "nativeAsset": "ETH", "decimals": 18 },
                        #   { "id": "1INCH_ETH", "name": "1INCH Token (Vested)", "type": "ERC20", "contractAddress": "0x03d1B1A56708FA298198DD5e23651a29B76a16d2", "nativeAsset": "ETH", "decimals": 18 },
                        #   { "id": "GALA", "name": "Gala V1", "type": "ERC20", "contractAddress": "0x15D4c048F83bd7e37d49eA4C83a07267Ec4203dA", "nativeAsset": "ETH", "decimals": 8 },
                        #   { "id": "GALA2", "name": "Gala V2", "type": "ERC20", "contractAddress": "0xd1d2Eb1B1e90B638588728b4130137D262C87cae", "nativeAsset": "ETH", "decimals": 8 }
                        # ]
                        #
                        # To avoid confusion do not use fireblocks api for such tokens
                        if symbol in tokens_from_fireblocks:
                            id, _ = tokens_from_fireblocks[symbol]
                            supported_tokens_id.pop(id)
                            tokens_from_fireblocks.pop(symbol)
                    else:
                        seen_tokens.add(symbol)
                        id = token["id"]
                        address = token["contractAddress"]

                        assert len(address) or token["type"] == "BASE_ASSET"

                        tokens_from_fireblocks[symbol] = (id, address)
                        supported_tokens_id[id] = symbol

            except Exception as ex:
                self.__logger.exception(f"Error in handling token={token} in the fireblocks response: %r", ex)

        return supported_tokens_id, tokens_from_fireblocks

    # supported_tokens_id => dict of : fireblocks_token_id -> token_symbol
    async def __get_withdrawal_address_whitelist_from_fireblocks(self, supported_tokens_id: dict) -> defaultdict(set):
        fireblocks_withdrawal_address_whitelist = defaultdict(set)
        response = await self.__fireblocks_api.get_internal_wallets()
        self.__logger.info(f"Fireblocks internal wallets response: {response}")
        # Sample Response:
        # [
        #   {
        #     "id": "1b738cdb-f080-49a4-95d8-433f12aa0aa5",
        #     "name": "gate_1_spot",
        #     "assets": [
        #         {
        #             "id": "ADS_ERC20",
        #             "status": "APPROVED",
        #             "address": "0x8BEe7340304a051B16ceCee05fB8c999Db3b65eD",
        #             "tag": "",
        #             "balance": "0",
        #             "lockedAmount": "0",
        #         },
        #         {
        #             "id": "QRDO",
        #             "status": "APPROVED",
        #             "address": "0x8BEe7340304a051B16ceCee05fB8c999Db3b65eD",
        #             "tag": "",
        #             "balance": "0",
        #             "lockedAmount": "0",
        #         },
        #     ]
        #   }
        # ]
        for account in response:
            try:
                for asset in account["assets"]:
                    try:
                        if (asset["id"] in supported_tokens_id) and (asset["status"] == "APPROVED"):
                            symbol = supported_tokens_id[asset["id"]]
                            fireblocks_withdrawal_address_whitelist[symbol].add(Web3.to_checksum_address(asset["address"]))
                    except Exception as ex:
                        self.__logger.exception(f"Error in handling asset={asset} in the fireblocks response: %r", ex)
            except Exception as e:
                self.__logger.exception(f"Error in handling account={account} in the fireblocks response: %r", e)

        return fireblocks_withdrawal_address_whitelist

    async def __get_whitelisted_withdrawal_addresses_and_tokens_from_fireblocks(self):
        while True:
            try:
                supported_tokens_id, tokens_from_fireblocks = await self.__get_supported_tokens_from_fireblocks()
                self.__dex._on_fireblocks_tokens_whitelist_refresh(tokens_from_fireblocks)

                fireblocks_withdrawal_address_whitelist = await self.__get_withdrawal_address_whitelist_from_fireblocks(supported_tokens_id)
                self.__dex._on_fireblocks_withdrawal_whitelist_refresh(fireblocks_withdrawal_address_whitelist)

                self.__first_value_fetched.set()
            except Exception as ex:
                self.__logger.exception(f"Error in getting whitelisted withdrawal addresses and tokens from fireblocks: %r", ex)
                await self.__pantheon.sleep(30)
                continue

            await self.__pantheon.sleep(120)
