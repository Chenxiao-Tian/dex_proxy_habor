import os

from .native_utils import sign_quote
from py_dex_common.dexes.dex_common import DexCommon

import concurrent.futures
from pyutils.exchange_apis.erc20web3_api import ERC20Token
from web3 import Web3
from pyutils.exchange_connectors import ConnectorType
from pyutils.gas_pricing.eth import GasPriceTracker, PriorityFee
from pantheon import Pantheon
from typing import Tuple
from py_dex_common.web_server import WebServer
import json
from eth_account.account import Account

from pyutils.exchange_connectors import ConnectorFactory, ConnectorType
from pyutils.exchange_apis import ApiFactory


class Native(DexCommon):
    def __init__(
        self, pantheon: Pantheon, config: dict, server: WebServer, event_sink
    ):
        super().__init__(pantheon, config, server, event_sink)
        
        api_factory = ApiFactory(ConnectorFactory(config["connectors"]))
        self._api = api_factory.create(self.pantheon, ConnectorType.Native)

        self.__chain_name = config['chain_name']
        self.__native_token = config['native_token']

        self.__gas_price_tracker = GasPriceTracker(pantheon, config['gas_price_tracker'])
        self.__eth_private_key = None
        self.__eth_public_key = None

        self.__pool_address = None

        self.order_req_id = 0
        self.__tokens_from_res_file = {}

        self.__process_pool = concurrent.futures.ProcessPoolExecutor(
            max_workers=config["max_signature_generators"]
        )

        self.__register_endpoints(server)

    def __register_endpoints(self, server: WebServer) -> None:
        server.register("POST", "/private/order-signature", self.__sign_order_request)
        server.register(
            'POST', '/private/wrap-unwrap-eth', self.__wrap_unwrap_eth)

    async def start(self, eth_private_key: str):
        self.__eth_private_key = eth_private_key
        self.__eth_public_key = Account.from_key(eth_private_key).address

        self.__load_whitelist()
        await self._api.initialize(
            private_key_or_mnemonic=eth_private_key,
            wallet_address=self.__eth_public_key,
            pool_contract_address=self.__pool_address,
            tokens_list=self.__tokens_from_res_file.values()
        )

        await super().start(eth_private_key)

        await self.__gas_price_tracker.start()
        await self.__gas_price_tracker.wait_gas_price_ready()

        max_nonce_cached = self._request_cache.get_max_nonce()
        self._api.initialize_starting_nonce(max_nonce_cached + 1)

        self.started = True

    def __load_whitelist(self):
        file_prefix = os.path.dirname(os.path.realpath(__file__))
        addresses_whitelists_file_path = f'{file_prefix}/../../resources/native_contracts_address.json'
        self._logger.debug(f'Loading addresses whitelists from {addresses_whitelists_file_path}')
        with open(addresses_whitelists_file_path, 'r') as contracts_address_file:
            contracts_address_json = json.load(contracts_address_file)[self.__chain_name]

            if 'pool_address' in contracts_address_json:
                self.__pool_address = Web3.to_checksum_address(contracts_address_json["pool_address"])

            tokens_list_json = contracts_address_json["tokens"]
            for token_json in tokens_list_json:
                symbol = token_json["symbol"]
                if symbol in self._withdrawal_address_whitelists_from_res_file:
                    raise RuntimeError(f'Duplicate token : {symbol} in contracts_address file')
                for withdrawal_address in token_json["valid_withdrawal_addresses"]:
                    self._withdrawal_address_whitelists_from_res_file[symbol].add(Web3.to_checksum_address(withdrawal_address))

                if symbol != self.__native_token:
                    self.__tokens_from_res_file[symbol] = ERC20Token(token_json["symbol"],
                                                                     Web3.to_checksum_address(token_json["address"]))

    def _on_tokens_whitelist_refresh(self, tokens: dict):
        for symbol, (_, address) in tokens.items():
            if len(address) == 0:
                assert symbol == self.__native_token
                continue

            address = Web3.to_checksum_address(address)
            if symbol in self.__tokens_from_res_file:
                if address != self.__tokens_from_res_file[symbol].address:
                    self._logger.error(f'Symbol={symbol} address did not match: API: {address} Resources File: {self.__tokens_from_res_file[symbol].address}')
                continue

            try:
                self._api._add_or_update_erc20_contract(symbol, address)
            except Exception as ex:
                self._logger.exception(f'Error in adding or updating ERC20 token (symbol={symbol}, address={address}): %r', ex)

    # We don't need to do anything special on a new client connection
    async def on_new_connection(self, _):
        return

    async def process_request(self, ws, request_id: str, method: str, params: dict):
        return False

    def __assert_order_request_schema(self, received_keys: list) -> None:
        expected_keys = [
            "quote_data"
        ]

        assert len(received_keys) == len(expected_keys), f"Request does not contain the correct set of fields. Expected [{', '.join(expected_keys)}]"
        for key in expected_keys: assert key in received_keys, f"Missing field({key}) in the request"

    async def __sign_order_request(
        self, path: str, params: dict, received_at_ms: int
    ) -> Tuple[int, dict]:
        try:
            req_id = self.order_req_id
            self.order_req_id += 1

            start = time.time()

            self._logger.debug(f"order request ({req_id}) to sign => {params}")

            self.__assert_order_request_schema(params.keys())

            msg_signature = await self.pantheon.loop.run_in_executor(self.__process_pool, sign_quote,
                                                                     self.__eth_private_key,
                                                                     self.__pool_address,
                                                                     params['quote_data'])

            end = time.time()
            sign_time = (end - start) * 1000

            self._logger.debug(f"order request ({req_id}) signature => {msg_signature}, at {end}, took {sign_time} ms")

            return 200, {"signer": self.__eth_public_key, "signature": msg_signature}

        except Exception as e:
            return 400, {"error": str(e)}

    async def _approve(self, request, gas_price_wei: int, nonce=None):
        return await self._api.approve(request.symbol, request.amount, request.gas_limit, gas_price_wei, nonce)

    async def _transfer(
            self,
            request,
            gas_price_wei: int,
            nonce: int = None,
    ):
        path = request.request_path
        symbol = request.symbol
        address_to = request.address_to
        amount = request.amount
        gas_limit = request.gas_limit

        if path == '/private/withdraw':
            assert address_to is not None
            return await self._api.withdraw(symbol, address_to, amount, gas_limit, gas_price_wei)
        else:
            assert False

    async def __wrap_unwrap_eth(self, path, params: dict, received_at_ms):
        client_request_id = ''
        try:
            client_request_id = params['client_request_id']

            if self._request_cache.get(client_request_id) is not None:
                return 400, {'error': {'message': f'client_request_id={client_request_id} is already known'}}

            request = params['request']
            assert request == 'wrap' or request == 'unwrap', 'Unknown request, should be either wrap or unwrap'
            amount = Decimal(params['amount'])
            gas_price_wei = int(params['gas_price_wei'])
            gas_limit = int(params['gas_limit'])

            wrap_unwrap = WrapUnwrapRequest(client_request_id, request, amount, gas_limit, received_at_ms)

            self._logger.debug(
                f'{"Wrapping" if wrap_unwrap.request == "wrap" else "Unwrapping"}={wrap_unwrap}, gas_price_wei={gas_price_wei}')
            self._request_cache.add(wrap_unwrap)

            self._request_cache.maybe_add_or_update_request_in_redis(client_request_id)

            if wrap_unwrap.request == "wrap":
                result = await self._api.wrap(wrapped_token_symbol='WETH', amount=wrap_unwrap.amount,
                                              gas_limit=wrap_unwrap.gas_limit,
                                              gas_price=gas_price_wei, nonce=wrap_unwrap.nonce)
            else:
                result = await self._api.unwrap(wrapped_token_symbol='WETH', amount=wrap_unwrap.amount,
                                                gas_limit=wrap_unwrap.gas_limit,
                                                gas_price=gas_price_wei, nonce=wrap_unwrap.nonce)

            wrap_unwrap.nonce = result.nonce
            if result.error_type == ErrorType.NO_ERROR:
                wrap_unwrap.tx_hashes.append((result.tx_hash, RequestType.TRANSFER.name))
                wrap_unwrap.used_gas_prices_wei.append(gas_price_wei)

                self._transactions_status_poller.add_for_polling(
                    result.tx_hash, client_request_id, RequestType.TRANSFER)
                self._request_cache.maybe_add_or_update_request_in_redis(client_request_id)

                return 200, {'tx_hash': result.tx_hash}
            else:
                self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
                return 400, {'error': {'code': result.error_type.value, 'message': result.error_message}}

        except Exception as e:
            self._logger.exception(f'Failed to handle wrap_unwrap request: %r', e)
            self._request_cache.finalise_request(
                client_request_id, RequestStatus.FAILED)
            return 400, {'error': {'message': repr(e)}}

    async def _amend_transaction(self, request, params, gas_price_wei):
        if request.request_type == RequestType.TRANSFER:
            return await self._api.withdraw(
                request.symbol, request.address_to, request.amount, request.gas_limit, gas_price_wei,
                nonce=request.nonce)
        elif request.request_type == RequestType.APPROVE:
            raise Exception('Unsupported request type for amending')
        elif request.request_type == RequestType.BRIDGE:
            raise Exception('Unsupported request type for amending')
        else:
            raise Exception('Unsupported request type for amending')

    async def _cancel_transaction(self, request, gas_price_wei):
        if request.request_type == RequestType.TRANSFER or request.request_type == RequestType.APPROVE:
            return await self._api.cancel_transaction(request.nonce, gas_price_wei)
        else:
            raise Exception(f"Cancelling not supported for the {request.request_type}")

    async def get_transaction_receipt(self, request, tx_hash):
        return await self._api.get_transaction_receipt(tx_hash)

    def _get_gas_price(self, request, priority_fee: PriorityFee):
        return self.__gas_price_tracker.get_gas_price(priority_fee=priority_fee)

    async def on_request_status_update(self, client_request_id, request_status, tx_receipt: dict, mined_tx_hash: str = None):
        super().on_request_status_update(client_request_id, request_status, tx_receipt, mined_tx_hash)

    async def _get_all_open_requests(self, path: str, params: dict, received_at_ms: int):
        return await super()._get_all_open_requests(path, params, received_at_ms)

    async def _cancel_all(self, path: str, params: dict, received_at_ms: int):
        try:
            assert params['request_type'] == 'TRANSFER' \
                   or params['request_type'] == 'APPROVE', \
                   'Unknown transaction type'

            request_type = RequestType[params['request_type']]

            self._logger.debug(f'Canceling all requests, request_type={request_type.name}')

            cancel_requested = []
            failed_cancels = []

            for request in self._request_cache.get_all(request_type):
                try:
                    gas_price_wei = self._get_gas_price(request, priority_fee=PriorityFee.Fast)

                    if request.request_status == RequestStatus.CANCEL_REQUESTED and \
                            request.used_gas_prices_wei[-1] >= gas_price_wei:
                        self._logger.info(
                            f'Not sending cancel request for client_request_id={request.client_request_id} as cancel with '
                            f'greater than or equal to the gas_price_wei={gas_price_wei} already in progress')
                        cancel_requested.append(request.client_request_id)
                        continue

                    gas_price_wei = max(gas_price_wei, int(1.1 * request.used_gas_prices_wei[-1]))

                    ok, reason = self._check_max_allowed_gas_price(gas_price_wei)
                    if not ok:
                        self._logger.error(
                            f'Not sending cancel request for client_request_id={request.client_request_id}: {reason}')
                        failed_cancels.append(request.client_request_id)
                        continue

                    self._logger.debug(f'Canceling={request}, gas_price_wei={gas_price_wei}')
                    result = await self._cancel_transaction(request, gas_price_wei)

                    if result.error_type == ErrorType.NO_ERROR:
                        request.request_status = RequestStatus.CANCEL_REQUESTED
                        request.tx_hashes.append((result.tx_hash, RequestType.CANCEL.name))
                        request.used_gas_prices_wei.append(gas_price_wei)

                        cancel_requested.append(request.client_request_id)

                        self._transactions_status_poller.add_for_polling(
                            result.tx_hash, request.client_request_id, RequestType.CANCEL)
                        self._request_cache.maybe_add_or_update_request_in_redis(request.client_request_id)
                    else:
                        failed_cancels.append(request.client_request_id)
                except Exception as ex:
                    self._logger.exception(f'Failed to cancel request={request.client_request_id}: %r', ex)
                    failed_cancels.append(request.client_request_id)
            return 400 if failed_cancels else 200, {'cancel_requested': cancel_requested, 'failed_cancels': failed_cancels}

        except Exception as e:
            self._logger.exception(f'Failed to cancel all: %r', e)
            return 400, {'error': {'message': str(e)}}
