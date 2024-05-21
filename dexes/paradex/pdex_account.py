import hashlib
import aiohttp
import ujson
import logging

from typing import Tuple

from eth_account import Account as EthAccount
from eth_account.messages import encode_structured_data
from .starknet_messages import StarknetMessages

from starkware.crypto.signature.signature import EC_ORDER
from starknet_py.net.signer.stark_curve_signer import KeyPair
from starknet_py.hash.selector import get_selector_from_name
from starknet_py.hash.address import compute_address
from starknet_py.common import int_from_bytes
from starknet_py.net.networks import Network
from starknet_py.net.full_node_client import FullNodeClient

from .helpers.account import Account as StarknetAccount
from .helpers.typed_data import TypedData

class PdexSystemConfig(object):
    def __init__(
        self,
        l1_chain_id: int,
        paraclear_account_proxy_hash: str,
        paraclear_account_hash: str,
        starknet_fullnode_rpc_url: str,
        starknet_chain_id: int
    ):
        self.l1_chain_id = l1_chain_id
        self.paraclear_account_proxy_hash = paraclear_account_proxy_hash
        self.paraclear_account_hash = paraclear_account_hash
        self.starknet_fullnode_rpc_url = starknet_fullnode_rpc_url
        self.starknet_chain_id = starknet_chain_id


    @staticmethod
    def from_json(json):
        return PdexSystemConfig(
            int(json["l1_chain_id"]),
            json["paraclear_account_proxy_hash"],
            json["paraclear_account_hash"],
            json["starknet_fullnode_rpc_url"],
            int_from_bytes(json["starknet_chain_id"].encode()),
        )


class PdexAccount(object):
    def __init__(self, eth_private_key: str, pdex_config: PdexSystemConfig):

        self.__eth_account = self.__init_eth_account(eth_private_key)
        self.__key_pair = self.__generate_key_pair(self.__eth_account.key.hex(), pdex_config)

        self.address = self.__generate_address(hex(self.__key_pair.public_key), pdex_config)

        self.__client = self.__get_account_client(pdex_config, self.address, self.__key_pair)
        self.__logger = logging.getLogger("PdexAccount")


    def get_private_key(self):
        return self.__key_pair.private_key


    def __init_eth_account(self, eth_private_key):
        EthAccount.enable_unaudited_hdwallet_features()
        return EthAccount.from_key(eth_private_key)


    @staticmethod
    def generate_private_key(
        eth_private_key: str, pdex_config: PdexSystemConfig
    ) -> int:
        stark_key_msg = StarknetMessages.stark_key(pdex_config.l1_chain_id)
        msg_signature = KeyUtils.sign_stark_key_msg(eth_private_key, stark_key_msg)
        seed = int(msg_signature[2: 64 + 2], 16)
        return KeyUtils.grind_key(seed, key_value_limit=EC_ORDER)


    def __generate_key_pair(
        self, eth_private_key: str, pdex_config: PdexSystemConfig
    ) -> KeyPair:
        private_key = self.generate_private_key(eth_private_key, pdex_config)
        return KeyPair.from_private_key(private_key)


    def __generate_address(
        self, public_key: str, pdex_config: PdexSystemConfig
    ) -> str:
        return KeyUtils.generateAddress(
            pdex_config.paraclear_account_proxy_hash,
            pdex_config.paraclear_account_hash,
            public_key
        )


    def __get_account_client(
        self,
        pdex_config: PdexSystemConfig,
        account_address: str,
        key_pair: KeyPair
    ):
        account_client = StarknetAccount(
            client = FullNodeClient(pdex_config.starknet_fullnode_rpc_url),
            address = account_address,
            key_pair = key_pair,
            chain = pdex_config.starknet_chain_id
        )

        return account_client


    def hash_msg(self, msg):
        return TypedData.from_dict(msg).message_hash(self.__client.address)


    def sign_msg(self, msg) -> str:
        raw_signature = self.__client.sign_message(msg)
        return f'["{raw_signature[0]}","{raw_signature[1]}"]'


    async def onboard_account(
        self, pdex_config: PdexSystemConfig, exchange_url_prefix: str
    ) -> None:
        msg = StarknetMessages.onboarding(pdex_config.starknet_chain_id)
        msg_signature = self.sign_msg(msg)

        headers = {
            "PARADEX-ETHEREUM-ACCOUNT": self.__eth_account.address,
            "PARADEX-STARKNET-ACCOUNT": self.address,
            "PARADEX-STARKNET-SIGNATURE": msg_signature
        }

        url = f"{exchange_url_prefix}/onboarding"
        body = {'public_key': hex(self.__client.signer.public_key)}

        async with aiohttp.ClientSession(json_serialize=ujson.dumps) as session:
            async with session.post(url, headers=headers, json=body) as response:
                status_code = response.status

                if status_code != 200:
                    response = await response.json()
                    raise Exception(f"Unable to onboard the starknet account. Exchange returned status_code({status_code}), error({response['error']}), details({response['message']})")


class KeyUtils(object):
    @staticmethod
    def sign_stark_key_msg(
        eth_private_key: int, stark_key_msg: dict
    ) -> str:
        encoded_msg = encode_structured_data(primitive=stark_key_msg)
        signed_msg = EthAccount.sign_message(encoded_msg, eth_private_key)
        return signed_msg.signature.hex()


    @staticmethod
    def grind_key(key_seed: int, key_value_limit: int) -> int:
        max_allowed_value = 2**256 - (2**256 % key_value_limit)
        current_index = 0

        def indexed_sha256(seed: int, index: int) -> int:
            def padded_hex(x: int) -> str:
                # Hex string should have an even
                # number of characters to convert to bytes.
                hex_str = hex(x)[2:]
                return hex_str if len(hex_str) % 2 == 0 else "0" + hex_str

            digest = hashlib.sha256(bytes.fromhex(padded_hex(seed) + padded_hex(index))).hexdigest()
            return int(digest, 16)

        key = indexed_sha256(seed=key_seed, index=current_index)
        while key >= max_allowed_value:
            current_index += 1
            key = indexed_sha256(seed=key_seed, index=current_index)

        return key % key_value_limit


    @staticmethod
    def generateAddress(
        proxy_contract_hash: str,
        account_class_hash: str,
        public_key: str
    ) -> str:

        calldata = [
            int(account_class_hash, 16),
            get_selector_from_name("initialize"),
            2,
            int(public_key, 16),
            0,
        ]

        address = compute_address(
            class_hash=int(proxy_contract_hash, 16),
            constructor_calldata=calldata,
            salt=int(public_key, 16),
        )

        return hex(address)
