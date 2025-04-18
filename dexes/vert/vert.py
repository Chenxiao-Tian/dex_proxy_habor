import concurrent.futures
import json
import os

import traceback

from pyutils.exchange_apis.dex_common import RequestType, RequestStatus, ErrorType, TransferRequest, ApproveRequest
from pyutils.exchange_apis.vertex_api import Collateral
from pyutils.exchange_apis.utils.vertex_signature_generator import EIP712Types

from web3 import Web3

from ..dex_common import DexCommon

from pyutils.exchange_connectors import ConnectorType
from pyutils.gas_pricing.eth import PriorityFee

from pantheon import Pantheon

# For type annotations
from decimal import Decimal
from typing import Union

from web_server import WebServer


class Vert(DexCommon):
    def __init__(
        self, pantheon: Pantheon, config: dict, server: WebServer, event_sink
    ):
        super().__init__(pantheon, ConnectorType.Vertex, config, server, event_sink)
        self.__register_endpoints(server)

        self.__chain_name = config["chain_name"]
        self.__whitelisted_subaccounts = {} # Sub alias -> sub id. E.g: 'vertex_1s1' -> '0x03cde1e0bc6c1e096505253b310cf454b0b462fb000000000000000000000001'
        self.__bridge_eid_by_network_name = {}

        self.__process_pool = concurrent.futures.ProcessPoolExecutor(
            max_workers=config["max_signature_generators"]
        )

    def __register_endpoints(self, server: WebServer) -> None:
        # server.register("POST", "/private/perp-to-spot-usdc-transfer", self.__transfer_usdc_from_perp_to_spot)
        server.register("POST", "/private/transfer-usdc-between-subaccounts", self.__transfer_usdc_between_subaccounts)
        server.register("POST", "/private/withdraw-collateral-from-subaccount-fast", self.__withdraw_collateral_from_subaccount_fast)
        server.register("POST", "/private/deposit-collateral-to-subaccount", self.__deposit_collateral_to_subaccount)
        server.register("POST", "/private/approve-deposit-collateral-to-subaccount", self.__approve_deposit_collateral_to_subaccount)
        server.register("POST", "/private/approve-bridge-spending", self.__approve_bridge_spending)
        server.register("POST", "/private/bridge-out", self.__bridge_out)

        server.register("POST", "/private/get-ws-auth-signature", self.__get_ws_auth_signature)
        server.register("POST", "/private/sign_order", self.__get_order_signature)
        server.register("POST", "/private/sign_cancel_order", self.__get_cancel_order_signature)
        server.register("POST", "/private/sign_cancel_all", self.__get_cancel_all_signature)

        server.register("GET", "/public/chain_name", self.__get_chain_name)

    def __load_whitelist_and_tokens(self) -> list:
        file_prefix = os.path.dirname(os.path.realpath(__file__))
        addresses_whitelists_file_path = f"{file_prefix}/../../resources/vert_contracts_address.json"

        self._logger.debug(f"Loading addresses whitelists from {addresses_whitelists_file_path}")

        token_details = []

        with open(addresses_whitelists_file_path, "r") as addresses_whitelists_file:
            addresses_whitelists_json = json.load(addresses_whitelists_file)[self.__chain_name]

            # Load subaccount whitelist
            whitelisted_subaccounts_json = addresses_whitelists_json["subaccounts"]
            for sub_alias, sub_id in whitelisted_subaccounts_json.items():
                # validate that sub_id is a valid 66 symbols long hex string
                if not sub_id.startswith("0x"):
                    sub_id = '0x' + sub_id
                if len(sub_id) != 66:
                    raise RuntimeError(f"Exchange subaccount invalid : {sub_id}")
                # try to convert from hex to make sure that there is no exception generated
                Web3.to_bytes(hexstr=sub_id)

                self._logger.debug(f"Adding mapping: {sub_alias}: {sub_id}")
                self.__whitelisted_subaccounts[sub_alias] = sub_id

            # Load token details
            tokens_json = addresses_whitelists_json["tokens"]
            for token in tokens_json:
                token_details.append(token)

            # Load token_withdrawal_addresses
            for token_json in tokens_json:
                symbol = token_json["name"]
                if symbol in self._withdrawal_address_whitelists_from_res_file:
                    raise RuntimeError(f"Duplicate token : {symbol} in contracts_address file")
                for withdrawal_address in token_json["valid_withdrawal_addresses"]:
                    self._withdrawal_address_whitelists_from_res_file[symbol].add(Web3.to_checksum_address(withdrawal_address))

            # Load network to layerzero eid mapping
            for network_name, eid in addresses_whitelists_json['bridge_eid_by_network_name'].items():
                self.__bridge_eid_by_network_name[network_name] = eid

        return token_details

    async def start(self, eth_private_key: Union[str, list]):
        token_details = self.__load_whitelist_and_tokens()

        await self._api.initialize(private_key=eth_private_key, token_details=token_details)

        await super().start(eth_private_key)

        max_nonce_cached = self._request_cache.get_max_nonce()
        self._api.initialize_starting_nonce(max_nonce_cached + 1)
        # self.started used in status endpoint in dex common
        self.started = True

    # We don't need to do anything special on a new client connection
    async def on_new_connection(self, _):
        return

    async def _amend_transaction(self, request, params, gas_price_wei):
        if request.request_type == RequestType.TRANSFER:
            if request.request_path == "/private/withdraw":
                return await self._api.withdraw(
                    request.symbol, request.address_to, request.amount, request.gas_limit, gas_price_wei, nonce=request.nonce
                )
            elif request.request_path == "/private/bridge-out":
                return await self._api.bridge(
                    request.dex_specific['dest_eid'], request.symbol, request.amount, request.nonce, request.gas_limit, gas_price_wei
                )
            elif request.request_path == "/private/deposit-collateral-to-subaccount":
                return await self._api.deposit_collateral_to_subaccount(
                    request.dex_specific['dest_acc'], Collateral(request.symbol, request.dex_specific['product_id']), request.amount,
                    request.nonce, request.gas_limit, gas_price_wei
                )
            else:
                raise Exception(f"Unsupported request_path={request.request_path} for amending transfer request")
        elif request.request_type == RequestType.APPROVE:
            if request.request_path == "/private/approve-deposit-collateral-to-subaccount":
                return await self._api.approve_collateral_deposit(
                    request.symbol, request.amount, request.nonce, request.gas_limit, gas_price_wei
                )
            if request.request_path == "/private/approve-bridge-spending":
                return await self._api.approve_bridge_spending(
                    request.dex_specific['dest_eid'], request.symbol, request.amount, request.nonce, request.gas_limit, gas_price_wei
                )
            else:
                raise Exception(f"Unsupported request_path={request.request_path} for amending approve request")
        else:
            raise Exception("Unsupported request type for amending")

    async def _approve(self, request, gas_price_wei: int, nonce=None):
        raise NotImplementedError

    async def _cancel_all(self, path: str, params: dict, received_at_ms: int):
        raise NotImplementedError

    def __is_subaccount_whitelisted_for_transfer(self, sub_alias: str, sub_id: str):
        if len(sub_id) != 66:
            return False, f'{sub_id} is not a valid subaccount id'

        # First 20 bytes of the sub_id is the wallet address
        checksum_addr = self._api._w3.to_checksum_address(sub_id[:42])
        if checksum_addr != self._api._wallet_address:
            return False, f'Wallet address associated with {sub_id} does not match dex_proxy wallet address'
        if sub_alias not in self.__whitelisted_subaccounts:
            return False, f'Subaccount {sub_alias} not whitelisted'

        configured_sub_id = self.__whitelisted_subaccounts[sub_alias]
        if sub_id != configured_sub_id:
            return False, f'Configured sub_id for sub_alias={sub_alias} does not match that in request.'
        return True, ''

    async def __transfer_usdc_between_subaccounts(self, path: str, params: dict, received_at_ms: int):
        try:
            src_acc_alias = params['src_acc_alias']
            dest_acc_alias = params['dest_acc_alias']
            src_acc_id = params['src_acc_id']
            dest_acc_id = params['dest_acc_id']
            amount = Decimal(params['amount'])

            ok, reason = self.__is_subaccount_whitelisted_for_transfer(src_acc_alias, src_acc_id)
            if not ok:
                return 400, {"error": {"message": reason}}

            ok, reason = self.__is_subaccount_whitelisted_for_transfer(dest_acc_alias, dest_acc_id)
            if not ok:
                return 400, {"error": {"message": reason}}

            result = await self._api.transfer_usdc_between_subaccounts(src_acc_id, dest_acc_id, amount)

            return 200, {"transfer-usdc-between-subaccounts": str(result)}
        except Exception as e:
            return 400, {"error": {"message": repr(e)}}

    async def __withdraw_collateral_from_subaccount_fast(self, path: str, params: dict, received_at_ms: int):
        try:
            src_acc_alias = params['src_acc_alias']
            src_acc_id = params['src_acc_id']
            collateral_name = params['collateral']
            product_id = params['product_id']

            ok, reason = self.__is_subaccount_whitelisted_for_transfer(src_acc_alias, src_acc_id)
            if not ok:
                return 400, {"error": {"message": reason}}

            amount = Decimal(params['amount'])
            result = await self._api.withdraw_collateral_from_subaccount_fast(src_acc_id,
                                                                              Collateral(collateral_name, product_id),
                                                                              amount)

            return 200, {"withdraw-collateral-from-subaccount-fast": str(result)}
        except Exception as e:
            return 400, {"error": {"message": repr(e)}}

    async def __deposit_collateral_to_subaccount(self, path: str, params: dict, received_at_ms: int):
        client_request_id = ""
        try:
            client_request_id = params["client_request_id"]
            dest_acc_alias = params['dest_acc_alias']
            dest_acc_id = params['dest_acc_id']
            collateral_name = params['collateral']
            product_id = params['product_id']
            amount = Decimal(params['amount'])

            gas_limit = int(params['gas_limit'])
            gas_price_wei = int(params['gas_price_wei'])

            ok, reason = self.__is_subaccount_whitelisted_for_transfer(dest_acc_alias, dest_acc_id)
            if not ok:
                return 400, {"error": {"message": reason}}

            transfer = TransferRequest(
                client_request_id=client_request_id,
                symbol=collateral_name,
                amount=amount,
                # Leaving this empty as the `address_to` is hardcoded in the
                # pyutils api call and is our l2 account address
                address_to="",
                # Unused
                gas_limit=gas_limit,
                request_path=path,
                received_at_ms=received_at_ms,
                dex_specific={
                    'dest_acc': dest_acc_id,
                    'product_id': product_id
                }
            )

            self._logger.info(f"Transferring={transfer}, request_path={path}")

            self._request_cache.add(transfer)

            result = await self._api.deposit_collateral_to_subaccount(dest_acc_id,
                                                                      Collateral(collateral_name, product_id),
                                                                      amount,
                                                                      gas_limit=gas_limit,
                                                                      gas_price=gas_price_wei)

            if result.error_type == ErrorType.NO_ERROR:
                transfer.nonce = result.nonce
                transfer.tx_hashes.append((result.tx_hash, RequestType.TRANSFER.name))
                transfer.used_gas_prices_wei.append(gas_price_wei)

                self._transactions_status_poller.add_for_polling(result.tx_hash, client_request_id, RequestType.TRANSFER)
                self._request_cache.maybe_add_or_update_request_in_redis(client_request_id)
                return 200, {"tx_hash": result.tx_hash}
            else:
                self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
                return 400, {"error": {"code": result.error_type.value, "message": result.error_message}}
        except Exception as e:
            self._logger.exception(f"Failed to transfer: %r", e)
            self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
            return 400, {"error": {"message": str(e)}}

    async def __approve_deposit_collateral_to_subaccount(self, path: str, params: dict, received_at_ms: int):
        client_request_id = ""
        try:
            client_request_id = params["client_request_id"]
            symbol = params["symbol"]
            amount = Decimal(params["amount"])

            gas_limit = int(params['gas_limit'])
            gas_price_wei = int(params['gas_price_wei'])

            approve = ApproveRequest(
                client_request_id=client_request_id,
                symbol=symbol,
                amount=amount,
                gas_limit=gas_limit,
                request_path=path,
                received_at_ms=received_at_ms,
            )

            self._logger.info(f"Approving={approve}, request_path={path}")

            self._request_cache.add(approve)

            result = await self._api.approve_collateral_deposit(symbol, amount,
                                                                gas_limit=gas_limit,
                                                                gas_price=gas_price_wei)

            if result.error_type == ErrorType.NO_ERROR:
                approve.nonce = result.nonce
                approve.tx_hashes.append((result.tx_hash, RequestType.APPROVE.name))
                approve.used_gas_prices_wei.append(gas_price_wei)
                self._transactions_status_poller.add_for_polling(result.tx_hash, approve.client_request_id, RequestType.APPROVE)
                self._request_cache.maybe_add_or_update_request_in_redis(approve.client_request_id)
                return 200, {"tx_hash": result.tx_hash}
            else:
                self._request_cache.finalise_request(approve.client_request_id, RequestStatus.FAILED)
                return 400, {"error": {"code": result.error_type.value, "message": result.error_message}}
        except Exception as e:
            self._logger.exception(f"Failed to approve: %r", e)
            self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
            return 400, {"error": {"message": str(e)}}

    async def __approve_bridge_spending(self, path: str, params: dict, received_at_ms: int):
        client_request_id = ""
        try:
            client_request_id = params["client_request_id"]
            symbol = params["symbol"]
            amount = Decimal(params["amount"])
            dest_chain = params["dest_chain"]

            gas_limit = int(params['gas_limit'])
            gas_price_wei = int(params['gas_price_wei'])

            if dest_chain not in self.__bridge_eid_by_network_name:
                return 400, {"error": {f"Unknown destination chain={dest_chain}"}}

            dest_eid = self.__bridge_eid_by_network_name[dest_chain]

            approve = ApproveRequest(
                client_request_id=client_request_id,
                symbol=symbol,
                amount=amount,
                gas_limit=gas_limit,
                request_path=path,
                received_at_ms=received_at_ms,
                dex_specific={
                    'dest_eid': dest_eid
                }
            )

            self._logger.info(f"Approving={approve}, request_path={path}")

            self._request_cache.add(approve)

            result = await self._api.approve_bridge_spending(dest_eid, symbol, amount,
                                                             gas_limit=gas_limit,
                                                             gas_price=gas_price_wei)

            if result.error_type == ErrorType.NO_ERROR:
                approve.nonce = result.nonce
                approve.tx_hashes.append((result.tx_hash, RequestType.APPROVE.name))
                approve.used_gas_prices_wei.append(gas_price_wei)
                self._transactions_status_poller.add_for_polling(result.tx_hash, approve.client_request_id, RequestType.APPROVE)
                self._request_cache.maybe_add_or_update_request_in_redis(approve.client_request_id)
                return 200, {"tx_hash": result.tx_hash}
            else:
                self._request_cache.finalise_request(approve.client_request_id, RequestStatus.FAILED)
                return 400, {"error": {"code": result.error_type.value, "message": result.error_message}}
        except Exception as e:
            self._logger.exception(f"Failed to approve bridge spending: %r", e)
            self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
            return 400, {"error": {"message": str(e)}}

    async def __bridge_out(self, path: str, params: dict, received_at_ms: int):
        client_request_id = ""
        try:
            client_request_id = params["client_request_id"]
            symbol = params["symbol"]
            amount = Decimal(params["amount"])
            dest_chain = params["dest_chain"]

            gas_limit = int(params['gas_limit'])
            gas_price_wei = int(params['gas_price_wei'])

            if dest_chain not in self.__bridge_eid_by_network_name:
                return 400, {"error": {f"Unknown destination chain={dest_chain}"}}

            dest_eid = self.__bridge_eid_by_network_name[dest_chain]

            transfer = TransferRequest(
                client_request_id=client_request_id,
                symbol=symbol,
                amount=amount,
                # Leaving this empty as the `address_to` is hardcoded in the
                # pyutils api call and is our wallet address
                address_to="",
                # Unused
                gas_limit=gas_limit,
                request_path=path,
                received_at_ms=received_at_ms,
                dex_specific={
                    'dest_eid': dest_eid
                }
            )

            self._logger.info(f"Bridging={transfer}, request_path={path}")

            self._request_cache.add(transfer)

            result = await self._api.bridge(dest_eid, symbol, amount,
                                            gas_limit=gas_limit,
                                            gas_price=gas_price_wei)

            if result.error_type == ErrorType.NO_ERROR:
                transfer.nonce = result.nonce
                transfer.tx_hashes.append((result.tx_hash, RequestType.TRANSFER.name))
                transfer.used_gas_prices_wei.append(gas_price_wei)
                self._transactions_status_poller.add_for_polling(result.tx_hash, client_request_id, RequestType.TRANSFER)
                self._request_cache.maybe_add_or_update_request_in_redis(client_request_id)
                return 200, {"tx_hash": result.tx_hash}
            else:
                self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
                return 400, {"error": {"code": result.error_type.value, "message": result.error_message}}
        except Exception as e:
            self._logger.exception(f"Failed to bridge out: %r", e)
            self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
            return 400, {"error": {"message": str(e)}}

    async def __get_chain_name(self, path: str, params: dict, received_at_ms: int):
        return 200, {'chain': self.__chain_name, "accounts": self.__whitelisted_subaccounts}

    async def __get_ws_auth_signature(self, path: str, params: dict, received_at_ms: int):
        try:
            self.assertRequiredFields(params, ['sender', 'expiration'])

            expiration_timestamp = params['expiration']
            sender = params['sender']

            message_to_sign = {
                'sender': Web3.to_bytes(hexstr=sender),
                'expiration': expiration_timestamp
            }

            signature = self._api.signature_generator.generate_signature(EIP712Types.AUTHENTICATE_STREAM, message_to_sign)

            return 200, {"signature": signature}

        except Exception as e:
            return 400, {"error": {"message": str(e)}}

    async def __get_order_signature(self, path: str, params: dict, received_at_ms: int):
        try:
            self.assertRequiredFields(params, ['price', 'amount', 'expiration', 'nonce', 'product_id', 'sender'])

            sender = params['sender']
            product_id = int(params['product_id'])

            order_message = {
                'sender': Web3.to_bytes(hexstr=sender),
                'priceX18': int(params['price']),
                'amount': int(params['amount']),
                'expiration': int(params['expiration']),
                'nonce': int(params['nonce'])
            }

            signature, digest = await self.pantheon.loop.run_in_executor(
                self.__process_pool,
                self._api.signature_generator.generate_order_signature,
                product_id, order_message
                )

            return 200, {"signature": signature, "digest": digest}

        except Exception as e:
            traceback.print_exc()
            return 400, {"error": {"message": str(e)}}

    async def __get_cancel_order_signature(self, path: str, params: dict, received_at_ms: int):
        try:
            self.assertRequiredFields(params, ['sender', 'product_id', 'digest', 'nonce'])

            sender = params['sender']
            product_id = int(params['product_id'])

            cancel_order_message = {
                'sender': Web3.to_bytes(hexstr=sender),
                'productIds': [product_id],
                'digests': [Web3.to_bytes(hexstr=params['digest'])],
                'nonce': int(params['nonce'])
            }

            signature = await self.pantheon.loop.run_in_executor(
                self.__process_pool,
                self._api.signature_generator.generate_signature,
                EIP712Types.CANCEL_ORDERS, cancel_order_message
                )

            return 200, {"signature": signature}

        except Exception as e:
            traceback.print_exc()
            return 400, {"error": {"message": str(e)}}

    async def __get_cancel_all_signature(self, path: str, params: dict, received_at_ms: int):
        try:
            self.assertRequiredFields(params, ['sender', 'nonce'])

            sender = params['sender']

            cancel_all_message = {
                'sender': Web3.to_bytes(hexstr=sender),
                'productIds': [],
                'nonce': int(params['nonce'])
            }

            signature = await self.pantheon.loop.run_in_executor(
                self.__process_pool,
                self._api.signature_generator.generate_signature,
                EIP712Types.CANCEL_PRODUCT_ORDERS, cancel_all_message
                )

            return 200, {"signature": signature}

        except Exception as e:
            traceback.print_exc()
            return 400, {"error": {"message": str(e)}}

    async def _cancel_transaction(self, request, gas_price_wei):
        raise NotImplementedError

    async def _get_all_open_requests(self, path: str, params: dict, received_at_ms: int):
        return await super()._get_all_open_requests(path, params, received_at_ms)

    async def on_request_status_update(self, client_request_id, request_status, tx_receipt: dict, mined_tx_hash: str = None):
        super().on_request_status_update(client_request_id, request_status, tx_receipt, mined_tx_hash)

    def _get_gas_price(self, request, priority_fee: PriorityFee):
        raise NotImplementedError

    async def _transfer( self, request, gas_price_wei: int, nonce: int = None):
        if request.request_path == "/private/withdraw":
            assert request.address_to is not None
            return await self._api.withdraw(request.symbol, request.address_to, request.amount,
                                            request.gas_limit, gas_price_wei)
        else:
            assert False

    async def get_transaction_receipt(self, request, tx_hash: str):
        return await self._api.get_transaction_receipt(tx_hash)

    async def process_request(self, ws, request_id: str, method: str, params: dict):
        raise NotImplementedError
