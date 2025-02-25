from collections import defaultdict
import concurrent.futures
import json
import os
import secrets
import time

import eth_account
from pyutils.exchange_apis.dex_common import RequestType, RequestStatus, ErrorType, TransferRequest
from pyutils.exchange_apis.erc20web3_api import ERC20Token
from web3 import Web3

from ..dex_common import DexCommon

from pyutils.exchange_connectors import ConnectorType
from pyutils.gas_pricing.eth import PriorityFee

from eth_account import Account

from pantheon import Pantheon

# For type annotations
from decimal import Decimal
from typing import Tuple, Optional, List, Union

from web_server import WebServer

from .signing import (OrderWire, order_request_to_order_wire,
                      order_wires_to_order_action, sign_l1_action,
                      sign_withdraw_from_bridge_action, sign_agent, sign_usd_class_transfer_action,
                      sign_spot_send)

HYPERLIQUID = 'Hyperliquid'

class Hype(DexCommon):
    def __init__(
        self, pantheon: Pantheon, config: dict, server: WebServer, event_sink
    ):
        super().__init__(pantheon, ConnectorType.Hype, config, server, event_sink)
        self.order_req_id = 0
        self.bridge_address = None
        self.vault_address = None
        self.coin_to_asset = None
        self.is_mainnet = False

        self.__register_endpoints(server)

        self.__exchange_url_prefix: Optional[str] = None
        self.__set_exchange_url_prefix(config)

        self.__exchange_token_refresh_interval_s: int = config["exchange_token_refresh_interval_s"]
        self.__reload_coin_definitions_interval_s: int = config["reload_coin_definitions_interval_s"]

        self.__chain_name = config['chain_name']
        self.__native_token = config['native_token']

        self.__process_pool = concurrent.futures.ProcessPoolExecutor(
            max_workers=config["max_signature_generators"]
        )

    def __set_exchange_url_prefix(self, config):
        base_uri = config["connectors"]["hype"]["rest"]["base_uri"]
        api_path = config["connectors"]["hype"]["rest"]["api_path"]
        self.__exchange_url_prefix = f"{base_uri}{api_path}"
        self.is_mainnet = 'testnet' not in base_uri

    def __register_endpoints(self, server: WebServer) -> None:
        server.register("POST", "/private/approve-agent", self.__approve_agent)
        server.register("POST", "/private/order-signature", self.__sign_order_request)
        server.register("POST", "/private/cancel-signature", self.__sign_cancel_order_request)
        server.register("POST", "/private/withdraw-from-exchange", self.__withdraw_from_exchange)
        server.register("POST", "/private/deposit-into-exchange", self.__deposit_into_exchange)
        server.register("POST", "/private/update-leverage", self.__update_leverage)
        server.register("POST", "/private/spot-to-perp-usdc-transfer", self.__transfer_usdc_from_spot_to_perp)
        server.register("POST", "/private/perp-to-spot-usdc-transfer", self.__transfer_usdc_from_perp_to_spot)
        server.register("POST", "/private/send-spot-token", self.__transfer_spot_to_external_wallet)

    async def start(self, eth_private_key: Union[str, list]):
        self.__symbol_address = {}
        self.__hype_withdrawal_address_whitelists_from_res_file = defaultdict(set)
        self.__tokens_from_res_file = {}

        self.__load_whitelist()

        def key_generator(keys_list):
            accounts = [Account.from_key(key) for key in keys_list]
            while True:
                for account in accounts:
                    yield account

        if isinstance(eth_private_key, list):
            default_key = eth_private_key[0]

            self.rotating_key = key_generator(eth_private_key)
        else:
            default_key = eth_private_key
            self.rotating_key = key_generator([eth_private_key])

        await self._api.initialize(private_key_or_mnemonic=default_key, bridge_address=self.bridge_address, tokens_list=self.__tokens_from_res_file.values())

        self._logger.info(f"wallet_address={self._api._wallet_address}")

        await self.coin_definitions()
        self.pantheon.spawn(self.reload_coin_definitions_loop())

        await super().start(default_key)

        max_nonce_cached = self._request_cache.get_max_nonce()
        self._api.initialize_starting_nonce(max_nonce_cached + 1)

        self.started = True

    async def coin_definitions(self):
        meta_info = await self._api.get_swaps_meta_info()
        previous_coin_definitions_count = len(self.coin_to_asset) if self.coin_to_asset is not None else 0
        self.coin_to_asset = {asset_info["name"]: asset for (asset, asset_info) in enumerate(meta_info['universe'])}
        self._logger.debug(f'Loaded {len(self.coin_to_asset)} definitions')
        if previous_coin_definitions_count != 0 and previous_coin_definitions_count != len(self.coin_to_asset):
            self._logger.debug(f'Coin definitions count changed: old value {previous_coin_definitions_count}')

    async def reload_coin_definitions_loop(self):
        while True:
            await self.pantheon.sleep(self.__reload_coin_definitions_interval_s)
            try:
                await self.coin_definitions()
                self._logger.debug('Coin definitions reloaded')
            except Exception as ex:
                self._logger.exception(f'Failed to reload coin definitions: %r', ex)

    def __load_whitelist(self):
        file_prefix = os.path.dirname(os.path.realpath(__file__))
        addresses_whitelists_file_path = f'{file_prefix}/../../resources/hype_contracts_address.json'
        self._logger.debug(f'Loading addresses whitelists from {addresses_whitelists_file_path}')
        with open(addresses_whitelists_file_path, 'r') as contracts_address_file:
            contracts_address_json = json.load(contracts_address_file)

            chain_data = contracts_address_json[self.__chain_name]

            self._withdrawal_address_whitelists_from_res_file = self.__process_tokens(chain_data["tokens"], self.__chain_name)

            self.bridge_address = Web3.to_checksum_address(chain_data["bridge_address"])

            hyperliquid_chain_data = contracts_address_json[HYPERLIQUID]

            self.__hype_withdrawal_address_whitelists_from_res_file = self.__process_tokens(hyperliquid_chain_data["tokens"], HYPERLIQUID)

    def __process_tokens(self, tokens_list_json, chain):
        withdraw_whitelist = defaultdict(set)
        for token_json in tokens_list_json:
            symbol = token_json["symbol"]
            if symbol in withdraw_whitelist:
                raise RuntimeError(f'Duplicate token : {symbol} in contracts_address file')

            if chain == HYPERLIQUID:
                self.__symbol_address[symbol] = token_json['address']

            for withdrawal_address in token_json["valid_withdrawal_addresses"]:
                    withdraw_whitelist[symbol].add(Web3.to_checksum_address(withdrawal_address))

            if symbol != self.__native_token and chain == self.__chain_name :
                self.__tokens_from_res_file[symbol] = ERC20Token(token_json["symbol"], Web3.to_checksum_address(token_json["address"]))
        return withdraw_whitelist

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
        # No matter what gas price we specify in our request Arbitrum always charge only base gas fees which is usually 0.01 GWei.
        # https://auros-group.slack.com/archives/C04258ZMMMF/p1726555641110039?thread_ts=1725590960.960719&cid=C04258ZMMMF
        # return 10 GWei
        return 10_000_000_000

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

    def __assert_cancel_order_by_ex_oid_schema(self, received_keys: list) -> None:
        expected_keys = [
            "asset",
            "oid"
        ]

        assert len(received_keys) == len(expected_keys), f"Sign cancel Request does not contain the correct set of fields. Expected [{', '.join(expected_keys)}]"
        for key in expected_keys:
            assert key in received_keys, f"Missing field({key}) in the Sign Cancel by ExchangeOrderId request"

    def __assert_cancel_order_by_cl_oid_schema(self, received_keys: list) -> None:
        expected_keys = [
            "asset",
            "cloid"
        ]

        assert len(received_keys) == len(expected_keys), f"Sign cancel Request does not contain the correct set of fields. Expected [{', '.join(expected_keys)}]"
        for key in expected_keys:
            assert key in received_keys, f"Missing field({key}) in the Sign Cancel by ClientOrderId request"

    def __assert_update_leverage(self, received_keys: list) -> None:
        expected_keys = [
            "coin",
            "is_cross",
            "leverage"
        ]

        assert len(received_keys) == len(expected_keys), f"Update Leverge request does not contain the correct set of fields. Expected [{', '.join(expected_keys)}]"
        for key in expected_keys:
            assert key in received_keys, f"Missing field({key}) in the Update Leverge request"

    def __assert_order_schema(self, received_keys: list) -> None:
        expected_keys = [
            "asset",
            "is_buy",
            "sz",
            "limit_px",
            "order_type",
            "reduce_only",
            "cloid"
        ]

        assert len(received_keys) == len(expected_keys), f"Request does not contain the correct set of fields. Expected [{', '.join(expected_keys)}]"
        for key in expected_keys: assert key in received_keys, f"Missing field({key}) in the request"

    def __create_cancel_by_ex_oid_action(self, orders: list[dict]) -> dict:
        return {
            "type": "cancel",
            "cancels": [
                {
                    "a": order["asset"],
                    "o": order["oid"]
                }
                for order in orders
            ]
        }

    def __create_cancel_by_cl_oid_action(self, orders: list[dict]) -> dict:
        return {
            "type": "cancelByCloid",
            "cancels": [
                {
                    "asset": order["asset"],
                    "cloid": order["cloid"]
                }
                for order in orders
            ]
        }

    async def __sign_cancel_order_request(
        self, path: str, params: dict, received_at_ms: int
    ) -> Tuple[int, dict]:
        try:
            req_id = self.order_req_id
            self.order_req_id += 1

            assert 'nonce' in params, 'Missing nonce field'

            processing_start_ts_ms = int(time.time() * 1_000)

            self._logger.debug(f"[sign_cancel] reqId=({req_id}), dexRecvTs={received_at_ms}, processingStartTs={processing_start_ts_ms}")

            assert "orders" in params, "Missing field `orders`"
            assert len(params["orders"]), "Empty `orders` array"

            cancel_by_exchange_order_id = False
            if "oid" in params["orders"][0]:
                cancel_by_exchange_order_id = True
                for order in params['orders']:
                    self.__assert_cancel_order_by_ex_oid_schema(order.keys())
            else:
                for order in params['orders']:
                    self.__assert_cancel_order_by_cl_oid_schema(order.keys())

            cancel_action = self.__create_cancel_by_ex_oid_action(params["orders"]) if cancel_by_exchange_order_id else self.__create_cancel_by_cl_oid_action(params["orders"])

            signature = await self.pantheon.loop.run_in_executor(
                self.__process_pool,
                sign_l1_action,
                next(self.rotating_key),
                cancel_action,
                self.vault_address,
                params['nonce'],
                self.is_mainnet,
            )

            processing_end_ts_ms = int(time.time() * 1000)

            dex_wait_ms = processing_start_ts_ms - received_at_ms
            signature_latency_ms = processing_end_ts_ms - processing_start_ts_ms

            # Only logging telemetry for a single order request
            # TODO: Think about how to log telemetry for a batch of orders
            if len(params["orders"]) == 1:
                id_kv = f"exOId={params['orders'][0]['oid']}" if cancel_by_exchange_order_id else f"clOId={params['orders'][0]['cloid']}"
                self._logger.info(f"stat=signTelem, op=C, {id_kv}, srvRcv={received_at_ms}, esSend=, delayFromESMs=, dexWaitMs={dex_wait_ms}, signLatencyMs={signature_latency_ms}")

            return 200, {"signature": signature}

        except Exception as e:
            return 400, {"error": str(e)}

    async def __approve_agent(self, path: str, params: dict, received_at_ms: int):
        agent_key = "0x" + secrets.token_hex(32)
        account = eth_account.Account.from_key(agent_key)
        timestamp = int(time.time() * 1000)
        action = {
            "type": "approveAgent",
            "agentAddress": account.address,
            "agentName": "Auros",
            "nonce": timestamp,
        }

        signature = sign_agent(self._api._account, action, self.is_mainnet)

        result = await self._api.send_action(action, signature, timestamp, self.vault_address)

        self._logger.debug(f"Response {str(result)}")

        if result['status'] == 'ok':
            return 200, {'tx_hash': ''}
        else:
            return 400, {'error': result['response']}

    async def __update_leverage(self, path: str, params: dict, received_at_ms: int):

        self.__assert_update_leverage(list(params.keys()))

        coin = params['coin']
        asset_index = self.coin_to_asset[coin]
        is_cross = params['is_cross']
        leverage = int(params['leverage'])
        timestamp = int(time.time() * 1000)

        action = {
            "type": "updateLeverage",
            "asset": asset_index,
            "isCross": is_cross,
            "leverage": leverage
        }

        signature = sign_l1_action(self._api._account, action, self.vault_address, timestamp, self.is_mainnet)

        result = await self._api.send_action(action, signature, timestamp, self.vault_address)

        self._logger.debug(f"Response {str(result)}")

        if result['status'] == 'ok':
            return 200, {'tx_hash': ''}
        else:
            return 400, {'error': result['response']}

    async def __sign_order_request(
        self, path: str, params: dict, received_at_ms: int
    ) -> Tuple[int, dict]:
        try:
            req_id = self.order_req_id
            self.order_req_id += 1

            assert 'orders' in params, 'Missing orders field'
            assert 'order_creation_ts_ms' in params, 'Missing order_creation_ts_ms field'

            processing_start_ts_ms = int(time.time() * 1_000)

            self._logger.debug(f"[sign_insert] reqId=({req_id}), dexRecvTs={received_at_ms}, processingStartTs={processing_start_ts_ms}")

            for order in params['orders']:
                self.__assert_order_schema(order.keys())

            order_wires: List[OrderWire] = [
                order_request_to_order_wire(order, order["asset"]) for order in params['orders']
            ]

            order_action = order_wires_to_order_action(order_wires)

            signature = await self.pantheon.loop.run_in_executor(
                self.__process_pool,
                sign_l1_action,
                next(self.rotating_key),
                order_action,
                self.vault_address,
                params['order_creation_ts_ms'],
                self.is_mainnet,
            )

            processing_end_ts_ms = int(time.time() * 1000)
            delay_from_es_ms = received_at_ms - int(params["order_creation_ts_ms"])
            dex_wait_ms = processing_start_ts_ms - received_at_ms
            signature_latency_ms = processing_end_ts_ms - processing_start_ts_ms

            self._logger.info(f"stat=signTelem, op=I, clOId={params['orders'][0]['cloid']}, srvRcv={received_at_ms}, esSend={params['order_creation_ts_ms']}, delayFromESMs={delay_from_es_ms}, dexWaitMs={dex_wait_ms}, signLatencyMs={signature_latency_ms}")

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

            action = {"destination": self._api._wallet_address, "amount": str(amount), "time": timestamp, "type": "withdraw3"}

            signature = sign_withdraw_from_bridge_action(self._api._account, action, self.is_mainnet)

            result = await self._api.withdraw_from_exchange(amount,
                                                              self._api._wallet_address,
                                                              timestamp,
                                                              "Mainnet" if self.is_mainnet else "Testnet",
                                                              "0x66eee",
                                                              signature)

            if result['status'] == 'ok':
                self._request_cache.finalise_request(client_request_id, RequestStatus.SUCCEEDED)
                return 200, {'tx_hash': ''}
            else:
                self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
                return 400, {'error': result['response']}

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
                self._request_cache.maybe_add_or_update_request_in_redis(client_request_id)
                return 200, {'tx_hash': result.tx_hash}
            else:
                self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
                return 400, {'error': {'code': result.error_type.value, 'message': result.error_message}}
        except Exception as e:
            self._logger.exception(f'Failed to transfer: %r', e)
            self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
            return 400, {'error': {'message': str(e)}}
        

    async def __transfer_usdc_from_spot_to_perp(self,
        path: str,
        params: dict,
        received_at_ms: int) -> Tuple[int, dict]:
        return await self.__transfer_usdc_between_spot_and_perp_util(path, params, received_at_ms, True)
    
    async def __transfer_usdc_from_perp_to_spot(self,
        path: str,
        params: dict,
        received_at_ms: int) -> Tuple[int, dict]:
        return await self.__transfer_usdc_between_spot_and_perp_util(path, params, received_at_ms, False)

    async def __transfer_usdc_between_spot_and_perp_util(
        self,
        path: str,
        params: dict,
        received_at_ms: int,
        to_perp: bool) -> Tuple[int, dict]:
        client_request_id = ''
        try:
            str_amount = str(params['amount'])
            symbol = 'USDC'
            if self.vault_address:
                str_amount += f" subaccount:{self.vault_address}"
            timestamp = int(time.time() * 1000)
            action = {
                "type": "usdClassTransfer",
                "amount": str_amount,
                "toPerp": to_perp,
                "nonce": timestamp,
            }
            client_request_id = params['client_request_id']
            
            if self._request_cache.get(client_request_id) is not None:
                return 400, {'error': {'message': f'client_request_id={client_request_id} is already known'}}
            
            signature = sign_usd_class_transfer_action(self._api._account, action, self.is_mainnet)

            amount = Decimal(params['amount'])

            transfer = TransferRequest(
                client_request_id=client_request_id,
                symbol=symbol,
                amount=amount,
                # Leaving this empty as the `address_to` is hardcoded in the
                # pyutils api call and is our l2 account address
                address_to="",
                gas_limit=0,
                request_path=path,
                received_at_ms=received_at_ms)

            self._logger.info(f'Transferring USDC from {"spot to perp" if to_perp else "perp to spot"} ={transfer}, request_path={path}')

            self._request_cache.add(transfer)

            result = await self._api.transfer_usdc_between_spot_and_perp(
                amount=str_amount,
                timestamp=timestamp,
                chain="Mainnet" if self.is_mainnet else "Testnet",
                signature_chain_id='0x66eee',
                signature=signature,
                to_perp=to_perp
            )  

            if result['status'] == 'ok':
                self._request_cache.finalise_request(client_request_id, RequestStatus.SUCCEEDED)
                return 200, {'status': 'ok'}
            else:
                self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
                return 400, {'error': {'code': result['error'], 'message': result}}
        except Exception as e:
            self._logger.exception(f'Failed to transfer: %r', e)
            self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
            return 400, {'error': {'message': str(e)}}

    async def __transfer_spot_to_external_wallet(self,  path: str,
        params: dict,
        received_at_ms: int):
        try:
            str_amount = str(params['amount'])
            client_request_id = params['client_request_id']
            destination = params['destination']
            token = params['token']

            ok, reason = self.__allow_spot_withdraw(client_request_id, token, destination)
            if not ok:
                return 400, {'error': {'message': reason}}

            if self.vault_address:
                str_amount += f" subaccount:{self.vault_address}"
            timestamp = int(time.time() * 1000)
            action = {
                "type": "spotSend",
                "token": f"{token}:{self.__symbol_address[token]}",
                "amount": str_amount,
                "time": timestamp,
                "destination": destination
            }

            if self._request_cache.get(client_request_id) is not None:
                return 400, {'error': {'message': f'client_request_id={client_request_id} is already known'}}

            signature = sign_spot_send(self._api._account, action, self.is_mainnet)

            amount = Decimal(params['amount'])

            transfer = TransferRequest(
                client_request_id=client_request_id,
                symbol=token,
                amount=amount,
                # Leaving this empty as the `address_to` is hardcoded in the
                # pyutils api call and is our l2 account address
                address_to="",
                gas_limit=0,
                request_path=path,
                received_at_ms=received_at_ms)

            self._request_cache.add(transfer)

            result = await self._api.send_spot_token(
                amount=str_amount,
                timestamp=timestamp,
                chain="Mainnet" if self.is_mainnet else "Testnet",
                signature_chain_id='0x66eee',
                signature=signature,
                destination=destination,
                token=f"{token}:{self.__symbol_address[token]}"
            )
            if result['status'] == 'ok':
                self._request_cache.finalise_request(client_request_id, RequestStatus.SUCCEEDED)
                return 200, {'status': 'ok'}
            else:
                self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
                return 400, {'error': {'code': result['status'], 'message': result}}
        except Exception as e:
            self._logger.exception(f'Failed to Spot Send: %r', e)
            self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
            return 400, {'error': {'message': str(e)}}

    def __allow_spot_withdraw(self, client_request_id, symbol, address_to):
        if symbol not in self.__hype_withdrawal_address_whitelists_from_res_file:
            self._logger.error(
                f'HIGH ALERT: client_request_id={client_request_id} tried to withdraw unknown token={symbol}')
            return False, f'Unknown token={symbol}'

        assert address_to is not None
        if Web3.to_checksum_address(address_to) not in self.__hype_withdrawal_address_whitelists_from_res_file[symbol]:
            self._logger.error(
                f'HIGH ALERT: client_request_id={client_request_id} tried to withdraw token={symbol} '
                f'to unknown address={address_to}')
            return False, f'Unknown withdrawal_address={address_to} for token={symbol}'

        return True, ''