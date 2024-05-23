import concurrent.futures
import json
import os
import time

from pyutils.exchange_apis.dex_common import RequestType, RequestStatus, ErrorType, TransferRequest
from pyutils.exchange_apis.erc20web3_api import ERC20Token
from web3 import Web3

from .types import Cloid
from ..dex_common import DexCommon

from pyutils.exchange_connectors import ConnectorType
from pyutils.gas_pricing.eth import GasPriceTracker, PriorityFee

from pantheon import Pantheon

# For type annotations
from decimal import Decimal
from typing import Tuple, Optional, List

from web_server import WebServer

from .signing import (OrderWire, order_request_to_order_wire,
                      order_wires_to_order_action, sign_l1_action,
                      sign_withdraw_from_bridge_action)


class Hype(DexCommon):
    def __init__(
        self, pantheon: Pantheon, config: dict, server: WebServer, event_sink
    ):
        super().__init__(pantheon, ConnectorType.Hype, config, server, event_sink)

        c = Cloid.from_int(123)

        self.__register_endpoints(server)

        self.__exchange_url_prefix: Optional[str] = None
        self.__set_exchange_url_prefix(config)

        self.__exchange_token_refresh_interval_s: int = config["exchange_token_refresh_interval_s"]

        self.__chain_name = config['chain_name']
        self.__native_token = config['native_token']

        self.__gas_price_tracker = GasPriceTracker(pantheon, config['gas_price_tracker'])

        self.__process_pool = concurrent.futures.ProcessPoolExecutor(
            max_workers=config["max_signature_generators"]
        )

        self.order_req_id = 0

        self.bridge_address = None
        self.vault_address = None
        self.coin_to_asset = None
        self.is_mainnet = False

    def __set_exchange_url_prefix(self, config):
        base_uri = config["connectors"]["hype"]["rest"]["base_uri"]
        api_path = config["connectors"]["hype"]["rest"]["api_path"]
        self.__exchange_url_prefix = f"{base_uri}{api_path}"
        self.is_mainnet = 'testnet' not in base_uri

    def __register_endpoints(self, server: WebServer) -> None:
        server.register("POST", "/private/order-signature", self.__sign_order_request)
        server.register("POST", "/private/cancel-signature", self.__sign_cancel_order_request)
        server.register("POST", "/private/withdraw-from-exchange", self.__withdraw_from_exchange)
        server.register("POST", "/private/deposit-into-exchange", self.__deposit_into_exchange)

    async def start(self, eth_private_key: str):
        self.__load_whitelist()

        await self._api.initialize(private_key_or_mnemonic=eth_private_key, bridge_address=self.bridge_address, tokens_list=self.__tokens_from_res_file.values())

        meta_info = await self._api.get_swaps_meta_info()
        self.coin_to_asset = {asset_info["name"]: asset for (asset, asset_info) in enumerate(meta_info['universe'])}

        await super().start(eth_private_key)

        await self.__gas_price_tracker.start()
        await self.__gas_price_tracker.wait_gas_price_ready()

        max_nonce_cached = self._request_cache.get_max_nonce()
        self._api.initialize_starting_nonce(max_nonce_cached + 1)

        self.started = True

    def __load_whitelist(self):
        file_prefix = os.path.dirname(os.path.realpath(__file__))
        addresses_whitelists_file_path = f'{file_prefix}/../../resources/hype_contracts_address.json'
        self._logger.debug(f'Loading addresses whitelists from {addresses_whitelists_file_path}')
        with open(addresses_whitelists_file_path, 'r') as contracts_address_file:
            contracts_address_json = json.load(contracts_address_file)[self.__chain_name]

            tokens_list_json = contracts_address_json["tokens"]
            self.__tokens_from_res_file = {}
            for token_json in tokens_list_json:
                symbol = token_json["symbol"]
                if symbol in self._withdrawal_address_whitelists_from_res_file:
                    raise RuntimeError(f'Duplicate token : {symbol} in contracts_address file')
                for withdrawal_address in token_json["valid_withdrawal_addresses"]:
                    self._withdrawal_address_whitelists_from_res_file[symbol].add(Web3.to_checksum_address(withdrawal_address))

                if symbol != self.__native_token:
                    self.__tokens_from_res_file[symbol] = ERC20Token(token_json["symbol"], Web3.to_checksum_address(token_json["address"]))

            self.bridge_address = Web3.to_checksum_address(contracts_address_json["bridge_address"])

    # We don't need to do anything special on a new client connection
    async def on_new_connection(self, _):
        return

    async def process_request(self, ws, request_id: str, method: str, params: dict):
        return False

    async def _approve(self, request, gas_price_wei: int, nonce=None):
        return await self._api.approve_deposit_into_exchange(
            request.symbol, request.amount, request.gas_limit, gas_price_wei, nonce
        )

    async def _transfer(
         self,
         request,
         gas_price_wei: int,
         nonce: int=None,
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

    async def _amend_transaction(self, request, params, gas_price_wei):
        if request.request_type == RequestType.TRANSFER:
            return await self._api.withdraw(
                request.symbol, request.address_to, request.amount, request.gas_limit, gas_price_wei,
                nonce=request.nonce)
        elif request.request_type == RequestType.APPROVE:
            return await self._api.approve_deposit_into_l1_bridge(request.symbol, request.amount, request.gas_limit, gas_price_wei,
                                           nonce=request.nonce)
        else:
            raise Exception('Unsupported request type for amending')

    async def _cancel_transaction(self, request, gas_price_wei):
        if request.request_type == RequestType.TRANSFER or request.request_type == RequestType.APPROVE:
            return await self._api.cancel_transaction(request.nonce, gas_price_wei)
        else:
            raise Exception(f"Cancelling not supported for the {request.request_type}")

    async def get_transaction_receipt(self, request, tx_hash: str):
        return await self._api.get_transaction_receipt(tx_hash)

    def _get_gas_price(self, request, priority_fee: PriorityFee):
        return self.__gas_price_tracker.get_gas_price(priority_fee=priority_fee)

    async def on_request_status_update(self, client_request_id, request_status, tx_receipt: dict, mined_tx_hash: str = None):
        await super().on_request_status_update(client_request_id, request_status, tx_receipt, mined_tx_hash)

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
                        self._request_cache.add_or_update_request_in_redis(request.client_request_id)
                    else:
                        failed_cancels.append(request.client_request_id)
                except Exception as ex:
                    self._logger.exception(f'Failed to cancel request={request.client_request_id}: %r', ex)
                    failed_cancels.append(request.client_request_id)
            return 400 if failed_cancels else 200, {'cancel_requested': cancel_requested, 'failed_cancels': failed_cancels}

        except Exception as e:
            self._logger.exception(f'Failed to cancel all: %r', e)
            return 400, {'error': {'message': str(e)}}

    def __assert_cancel_order_schema(self, received_keys: list) -> None:
        expected_keys = [
            "coin",
            "oid"
        ]

        assert len(received_keys) == len(expected_keys), f"Sign cancel Request does not contain the correct set of fields. Expected [{', '.join(expected_keys)}]"
        for key in expected_keys:
            assert key in received_keys, f"Missing field({key}) in the Sign Cancel request"

    def __assert_order_schema(self, received_keys: list) -> None:
        expected_keys = [
            "coin",
            "is_buy",
            "sz",
            "limit_px",
            "order_type",
            "reduce_only",
            "cloid"
        ]

        assert len(received_keys) == len(expected_keys), f"Request does not contain the correct set of fields. Expected [{', '.join(expected_keys)}]"
        for key in expected_keys: assert key in received_keys, f"Missing field({key}) in the request"

    async def __sign_cancel_order_request(
        self, path: str, params: dict, received_at_ms: int
    ) -> Tuple[int, dict]:
        try:
            req_id = self.order_req_id
            self.order_req_id += 1

            start = time.time()

            assert 'nonce' in params, 'Missing nonce field'

            self._logger.debug(f"cancel order request ({req_id}) received at {start}")

            for order in params['orders']:
                self.__assert_cancel_order_schema(order.keys())

            cancel_action = {
                "type": "cancel",
                "cancels": [
                    {
                        "a": self.coin_to_asset[cancel["coin"]],
                        "o": cancel["oid"],
                    }
                    for cancel in params['orders']
                ]
            }

            signature = await self.pantheon.loop.run_in_executor(
                self.__process_pool,
                sign_l1_action,
                self._api._account,
                cancel_action,
                self.vault_address,
                params['nonce'],
                self.is_mainnet,
            )

            return 200, {"signature": signature}

        except Exception as e:
            return 400, {"error": str(e)}

    async def __sign_order_request(
        self, path: str, params: dict, received_at_ms: int
    ) -> Tuple[int, dict]:
        try:
            req_id = self.order_req_id
            self.order_req_id += 1

            start = time.time()

            assert 'orders' in params, 'Missing orders field'
            assert 'order_creation_ts_ms' in params, 'Missing order_creation_ts_ms field'

            self._logger.debug(f"order request ({req_id}) received at {start}")

            for order in params['orders']:
                self.__assert_order_schema(order.keys())

            order_wires: List[OrderWire] = [
                order_request_to_order_wire(order, self.coin_to_asset[order["coin"]]) for order in params['orders']
            ]

            order_action = order_wires_to_order_action(order_wires)

            signature = await self.pantheon.loop.run_in_executor(
                self.__process_pool,
                sign_l1_action,
                self._api._account,
                order_action,
                self.vault_address,
                params['order_creation_ts_ms'],
                self.is_mainnet,
            )

            return 200, {"signature": signature}

        except Exception as e:
            return 400, {"error": str(e)}

    async def __withdraw_from_exchange(
            self, path: str, params: dict, received_at_ms: int
    ) -> Tuple[int, dict]:
        client_request_id = ''

        try:
            symbol = params['symbol']
            client_request_id = params['client_request_id']
            if self._request_cache.get(client_request_id) is not None:
                return 400, {'error': {'message': f'client_request_id={client_request_id} is already known'}}

            amount = str(params['amount'])

            transfer = TransferRequest(
                client_request_id=client_request_id,
                symbol=symbol,
                amount=Decimal(params['amount']),
                # Leaving this empty as the `address_to` is hardcoded in the
                # pyutils api call
                address_to="",
                gas_limit=0,
                request_path=path,
                received_at_ms=received_at_ms)

            self._logger.info(f'Transferring={transfer}, request_path={path}')

            self._request_cache.add(transfer)

            timestamp = int(time.time() * 1000)
            payload = {
                "destination": self._api._wallet_address,
                "usd": amount,
                "time": timestamp
            }

            signature = sign_withdraw_from_bridge_action(self._api._account, payload, self.is_mainnet)

            result = await self._api.withdraw_from_exchange(amount,
                                                              self._api._wallet_address,
                                                              timestamp,
                                                              "Arbitrum" if self.is_mainnet else "ArbitrumTestnet",
                                                              self.vault_address,
                                                              signature)

            if result['status'] == 'ok':
                self._request_cache.finalise_request(client_request_id, RequestStatus.SUCCEEDED)
                return 200, {'tx_hash': ''}
            else:
                self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
                return 400, {'error': {'code': result.error_type.value, 'message': result.error_message}}

        except Exception as e:
            self._logger.exception(f'Failed to transfer: %r', e)
            self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
            return 400, {'error': {'message': str(e)}}

    async def __deposit_into_exchange(
        self,
        path: str,
        params: dict,
        received_at_ms: int
    ) -> Tuple[int, dict]:
        client_request_id = ''
        try:
            symbol = params['symbol']

            client_request_id = params['client_request_id']
            if self._request_cache.get(client_request_id) is not None:
                return 400, {'error': {'message': f'client_request_id={client_request_id} is already known'}}

            amount = Decimal(params['amount'])
            gas_limit = int(params['gas_limit'])

            gas_price_wei = int(params['gas_price_wei'])
            ok, reason = self._check_max_allowed_gas_price(gas_price_wei)
            if not ok:
                return 400, {'error': {'message': reason}}

            transfer = TransferRequest(
                client_request_id=client_request_id,
                symbol=symbol,
                amount=amount,
                # Leaving this empty as the `address_to` is hardcoded in the
                # pyutils api call and is our l2 account address
                address_to="",
                gas_limit=gas_limit,
                request_path=path,
                received_at_ms=received_at_ms)

            self._logger.info(f'Transferring={transfer}, request_path={path}, gas_price_wei={gas_price_wei}')

            self._request_cache.add(transfer)

            result = await self._api.deposit_into_exchange(
                symbol,
                amount,
                gas_limit,
                gas_price_wei
            )

            if result.error_type == ErrorType.NO_ERROR:
                transfer.nonce = result.nonce
                transfer.tx_hashes.append((result.tx_hash, RequestType.TRANSFER.name))
                transfer.used_gas_prices_wei.append(gas_price_wei)

                self._transactions_status_poller.add_for_polling(
                    result.tx_hash, client_request_id, RequestType.TRANSFER)
                self._request_cache.add_or_update_request_in_redis(client_request_id)
                return 200, {'tx_hash': result.tx_hash}
            else:
                self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
                return 400, {'error': {'code': result.error_type.value, 'message': result.error_message}}
        except Exception as e:
            self._logger.exception(f'Failed to transfer: %r', e)
            self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
            return 400, {'error': {'message': str(e)}}
