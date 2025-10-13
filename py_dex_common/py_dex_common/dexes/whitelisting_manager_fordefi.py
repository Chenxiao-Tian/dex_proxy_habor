import asyncio
import logging
import string

from collections import defaultdict
from typing import Tuple
from web3 import Web3

from pantheon import Pantheon

from pyutils.exchange_apis.fordefi_api import FordefiApi
from pyutils.exchange_connectors.fordefi_connector import FordefiConnector, FordefiConfiguration


def is_ascii_letters_only(s: str) -> bool:
    return all(ch in string.ascii_letters for ch in s)


class WhitelistingManagerFordefi:
    base_ex_msg = f"Error in getting whitelisted withdrawal addresses and tokens from fordefi: %r"
    def __init__(self, pantheon: Pantheon, dex, config: dict):
        self.__pantheon = pantheon
        self.__dex = dex
        self.__config: dict = config["fordefi"]
        self.__trusted_token_addresses = self.__config.get('trusted_token_addresses', {})
        self.__chain_type = None
        self.__native_currency = None

        self.__poll_interval_s: int = int(self.__config.get("poll_interval_s", 600))

        self.__logger = logging.getLogger("whitelisting_manager_fordefi")
        self.__first_value_fetched = asyncio.Event()

        self.__apis: dict[str, FordefiApi] = {}
        
        for connector_name in self.__config.get("connectors"):
            fordefi_config = FordefiConfiguration(config.get("connectors").get(connector_name))
            connector = FordefiConnector(pantheon, fordefi_config)
            self.__apis[connector_name] = FordefiApi(pantheon, connector)

    async def start(self):
        self.__logger.info(f"Polling every {self.__poll_interval_s}s")
        self.__pantheon.spawn(self.__get_whitelisted_withdrawal_addresses_and_tokens())
        await self.__first_value_fetched.wait()
    
    def __parse_token(self, token_info: dict):
        asset = token_info.get('asset')
        # Fallback for tokens like TON
        if not asset:
            asset = token_info.get('priced_asset', {}).get('asset_info')
            if not asset:
                return None
        return self.__parse_token_details(asset)

    def __parse_token_details(self, asset: dict):
        if 'chain' in asset['asset_identifier']:
            chain = asset['asset_identifier']['chain']
        elif 'chain' in asset['asset_identifier']['details']:
            chain = asset['asset_identifier']['details']['chain']

        chain_type = chain['chain_type']
        token_type = asset['asset_identifier']['details']['type']
        is_native = token_type == 'native'
        # remove all non-alphabetic characters to get symbol
        symbol = "".join([ch for ch in asset['symbol'] if ch.isalpha()])
        token = {
            'id': asset['id'],
            'chain_type': chain_type,
            'chain': chain['unique_id'],
            'native_asset': chain['native_currency_symbol'],
            'type': token_type,
            'symbol': symbol,
            'address': None
        }
        if not is_native:
            if chain_type == 'solana':
                token['address'] = asset['asset_identifier']['details']['token']['address']
            elif chain_type == 'evm':
                token_item = asset['asset_identifier']['details']['token']
                if 'contract' in token_item:
                    token['address'] = token_item['contract']['token']['address']['hex_repr']
                else:
                    token['address'] = token_item['hex_repr']
            elif chain_type == 'cosmos':
                # no examples from API
                return None
            elif chain_type == 'sui':
                token['address'] = asset['asset_identifier']['details']['coin']['coin_type']
            elif chain_type == 'utxo':
                # no examples from API
                return None
        return token

    async def __get_supported_tokens(self, api: FordefiApi) -> Tuple[dict, dict]:
        # dict of : token_symbol -> (token_id, token_address)
        tokens = {}
        # dict of : token_id -> token_symbol
        supported_tokens_id = {}

        response = []
        async for page in api.get_list_assets():
            response.extend(page['owned_assets'])
        self.__logger.debug(f"Fordefi supported assets response: {response}")

        seen_tokens = set()
        seen_ids = set()
        for token in response:
            try:
                token_info = self.__parse_token(token)
                if token_info is None:
                    self.__logger.warning("Cannot parse token=%s", token)
                    continue

                if token_info['symbol'] in self.__trusted_token_addresses:
                    if token_info['address'] != self.__trusted_token_addresses[token_info['symbol']]:
                        continue

                if not is_ascii_letters_only(token_info['symbol']):
                    # for instance we can't accept USDC with Cyrillic C
                    continue

                if token_info["chain"] != self.__config["blockchain"]:
                    continue

                if token_info["type"] not in self.__config["token_types"] or token_info["chain"] != self.__config["blockchain"]:
                    continue
                if self.__chain_type is None:
                    self.__chain_type = token_info['chain_type']
                if self.__native_currency is None:
                    self.__native_currency = token_info['native_asset']
                if self.__chain_type != token_info['chain_type']:
                    continue
                self.__logger.debug("Processing %s (%s) %s %s %s",
                                   token_info["symbol"], token_info["symbol"].encode("utf-8"),
                                   token_info["type"], token_info['id'], token_info['address'])
                if token_info["symbol"] in seen_tokens:
                    # Two or more tokens may have same symbol
                    # e.g:
                    # USDC erc20 evm_ethereum_mainnet 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48
                    # USDC erc20 evm_ethereum_mainnet 0x134E779aBde0acF3d2FfE5a80B90468e5c212eBa
                    #
                    # To avoid confusion do not use api for such tokens
                    if token_info["symbol"] in tokens:
                        id, _ = tokens[token_info["symbol"]]
                        supported_tokens_id.pop(id)
                        tokens.pop(token_info["symbol"])
                        self.__logger.debug("Confusion symbol: %s - deleted", token_info["symbol"])
                elif token_info['id'] in seen_ids:
                    self.__logger.debug("Confusion ID: %s -> %s", token_info["symbol"], token_info['id'])
                    # same confusion with ids
                    if token_info['id'] in supported_tokens_id:
                        symbol = supported_tokens_id[token_info['id']]
                        supported_tokens_id.pop(token_info['id'])
                        tokens.pop(symbol)
                        self.__logger.debug("Deleted %s %s (%s)", token_info['id'], token_info["symbol"], symbol)
                else:
                    seen_tokens.add(token_info["symbol"])
                    tokens[token_info['symbol']] = (token_info['id'], token_info['address'])
                    supported_tokens_id[token_info['id']] = token_info['symbol']
                    self.__logger.debug("Added %s %s", token_info['id'], token_info['symbol'])

            except Exception as ex:
                self.__logger.exception(f"Error in handling token={token} in response: %r", ex)
                raise ex

        return supported_tokens_id, tokens

    # supported_tokens_id => dict of : token_id -> token_symbol
    async def __get_withdrawal_address_whitelist(self, api: FordefiApi, groups: list[str], supported_tokens_id: dict) -> defaultdict:
        withdrawal_address_whitelist = defaultdict(set)
        response = []
        async for page in api.get_list_contacts(address_group_ids=groups):
            response.extend(page['contacts'])
        self.__logger.debug(f"Fordefi addressbook contacts response: {response}")

        for contact in response:
            try:
                if contact['state'] != 'active':
                    continue
                chains = contact.get('chains')
                if chains is None:
                    chains = [contact['chain']]
                if not chains and self.__chain_type != contact['chain_type']:
                    continue
                if not chains: # Any EVM
                    chains = [{
                        'chain_type': contact['chain_type'],
                        'unique_id': self.__config["blockchain"],
                        'native_currency_symbol': self.__native_currency,
                    }]
                chains_filtered = [chain for chain in chains if chain['unique_id'] == self.__config["blockchain"]]
                if len(chains_filtered) != 1:
                    continue
                chain = chains_filtered[0]
                whitelisted_tokens = self.__get_whitelisted_tokens_for_address(contact)
                address = self.__parse_address(chain['chain_type'], contact["address"])
                self.__logger.debug("Address: %s -> [native=%s] + [tokens=%s]",
                                    address, chain['native_currency_symbol'],
                                    list(supported_tokens_id.values() if whitelisted_tokens is None else whitelisted_tokens.keys()))
                if whitelisted_tokens is None:
                    withdrawal_address_whitelist[chain['native_currency_symbol']].add(address)
                #else:
                    # not clear if native currency can appears in 'asset_infos' list
                    # TODO - test this
                for token_id, symbol in supported_tokens_id.items():
                    if whitelisted_tokens is None:
                        # Any
                        withdrawal_address_whitelist[symbol].add(address)
                    elif symbol in whitelisted_tokens:
                        whitelisted_token = whitelisted_tokens[symbol]
                        if whitelisted_token['id'] == token_id:
                            withdrawal_address_whitelist[symbol].add(address)
            except Exception as e:
                self.__logger.exception(f"Error in handling contact={contact} in response: %r", e)

        return withdrawal_address_whitelist
    

    def __get_whitelisted_tokens_for_address(self, contact: dict):
        whitelisted_tokens_list = [self.__parse_token_details(item) for item in contact['asset_infos']]
        if not whitelisted_tokens_list:
            return None
        whitelisted_tokens = {}
        bad_tokens = set()
        for item in whitelisted_tokens_list:
            if item['symbol'] in bad_tokens:
                continue
            if item['symbol'] in self.__trusted_token_addresses and item['address'] != self.__trusted_token_addresses[item['symbol']]:
                continue
            if item['symbol'] in whitelisted_tokens:
                # already added, let's remove both to avoid confusion
                bad_tokens.add(item['symbol'])
                del whitelisted_tokens[item['symbol']]
            whitelisted_tokens[item['symbol']] = item
        return whitelisted_tokens

    def __parse_address(self, chain_type: str, address):
        if chain_type == 'evm':
            return Web3.to_checksum_address(address)
        return address
    
    def __merge_tokens(self, supported_tokens_id: dict, tokens: dict, _supported_tokens_id: dict, _tokens: dict, bad_supported_token_ids: set, bad_tokens: set):
        new_bad_token_ids = set()
        new_bad_tokens = set()
        for token_id, token_symbol in _supported_tokens_id.items():
            if token_id in bad_supported_token_ids:
                continue
            if token_id not in supported_tokens_id:
                supported_tokens_id[token_id] = token_symbol
            elif supported_tokens_id[token_id] != token_symbol:
                self.__logger.debug("Token symbol mismatch: token_id=%s, symbols=(%s vs %s)",
                                      token_id, supported_tokens_id[token_id], token_symbol)
                bad_supported_token_ids.add(token_id)
                new_bad_token_ids.add(token_id)
        for token_symbol, (token_id, token_address) in _tokens.items():
            if token_symbol in bad_tokens:
                continue
            if token_symbol not in tokens:
                tokens[token_symbol] = (token_id, token_address)
            elif tokens[token_symbol] != (token_id, token_address):
                self.__logger.debug("Token id mismatch: symbol=%s, symbols=(%s vs %s)",
                                      token_symbol, tokens[token_symbol], (token_id, token_address))
                bad_tokens.add(token_symbol)
                new_bad_tokens.add(token_symbol)

        for token_id in new_bad_token_ids:
            if token_id in supported_tokens_id:
                token_symbol = supported_tokens_id[token_id]
                supported_tokens_id.pop(token_id)
                tokens.pop(token_symbol, None)
        for token_symbol in new_bad_tokens:
            if token_symbol in tokens:
                token_id = tokens[token_symbol][0]
                tokens.pop(token_symbol)
                supported_tokens_id.pop(token_id, None)

                
    def __merge_withdrawal_address_whitelist(self,
                                             withdrawal_address_whitelist: defaultdict,
                                             _withdrawal_address_whitelist: defaultdict):
        for symbol, addresses_list in _withdrawal_address_whitelist.items():
            for address in addresses_list:
                if address not in withdrawal_address_whitelist[symbol]:
                    withdrawal_address_whitelist[symbol].add(address)

    async def __get_whitelisted_withdrawal_addresses_and_tokens(self):
        while True:
            self.__logger.info("Refreshing withdrawal addresses and tokens")
            supported_tokens_id, tokens = {}, {}
            bad_supported_tokens_id, bad_tokens = set(), set()
            withdrawal_address_whitelist = defaultdict(set)
            try:
                for api_name, api in self.__apis.items():
                    self.__logger.info("Fetching tokens from %s", api_name)
                    _supported_tokens_id, _tokens = await self.__get_supported_tokens(api)
                    groups = self.__config.get("groups", {}).get(api_name, {}).values()
                    group_names = self.__config.get("groups", {}).get(api_name, {}).keys()
                    self.__logger.info("Fetching addresses from %s (groups=%s)", api_name, list(group_names))
                    self.__merge_tokens(supported_tokens_id, tokens, _supported_tokens_id, _tokens, bad_supported_tokens_id, bad_tokens)
                    _withdrawal_address_whitelist = await self.__get_withdrawal_address_whitelist(api, groups, supported_tokens_id)
                    self.__merge_withdrawal_address_whitelist(withdrawal_address_whitelist, _withdrawal_address_whitelist)
                if bad_supported_tokens_id or bad_tokens:
                    self.__logger.warning("Failed to process token_ids: %s, tokens: %s", bad_supported_tokens_id, bad_tokens)
                self.__dex._on_tokens_whitelist_refresh(tokens)
                self.__dex._on_withdrawal_whitelist_refresh(withdrawal_address_whitelist)
            except asyncio.TimeoutError as timeout_ex:
                self.__logger.debug(WhitelistingManagerFordefi.base_ex_msg, timeout_ex)
                await self.__pantheon.sleep(30)
                continue
            except Exception as ex:
                self.__logger.exception(WhitelistingManagerFordefi.base_ex_msg, ex)
                await self.__pantheon.sleep(30)
                continue
            self.__first_value_fetched.set()
            await self.__pantheon.sleep(self.__poll_interval_s)
