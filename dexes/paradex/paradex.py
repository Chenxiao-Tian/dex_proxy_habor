import aiohttp
import ujson
import concurrent.futures
import os
from web3 import Web3
from ..dex_common import DexCommon
from .pdex_account import PdexAccount, PdexSystemConfig
from .jwt import JWT
from .starknet_messages import StarknetMessages

from starknet_py.net.client_models import TransactionStatus, TransactionReceipt

from pyutils.exchange_connectors import ConnectorFactory, ConnectorType
from pyutils.exchange_apis import ApiFactory
from pyutils.gas_pricing.eth import GasPriceTracker, PriorityFee
from pyutils.exchange_apis.dex_common import *

from pyutils.exchange_apis.paradex_api import *

from pantheon import Pantheon

# For type annotations
from decimal import Decimal
from typing import Tuple, Optional

from web_server import WebServer


class Paradex(DexCommon):
    def __init__(
        self, pantheon: Pantheon, config: dict, server: WebServer, event_sink
    ):
        super().__init__(pantheon, ConnectorType.Paradex, config, server, event_sink)

        self.__register_endpoints(server)

        self.__pdex_config: Optional[PdexSystemConfig] = None
        self.__pdex_account: Optional[PdexAccount] = None

        self.__exchange_url_prefix: Optional[str] = None
        self.__set_exchange_url_prefix(config)

        self.__exchange_token_refresh_interval_s: int = config["exchange_token_refresh_interval_s"]
        self.__jwt: Optional[JWT] = None

        self.__chain_name = config['chain_name']
        self.__native_token = config['native_token']

        self.__gas_price_tracker = GasPriceTracker(pantheon, config['gas_price_tracker'])

        self.__process_pool = concurrent.futures.ProcessPoolExecutor(
            config["max_signature_generators"]
        )

    def __set_exchange_url_prefix(self, config):
        base_uri = config["connectors"]["paradex"]["rest"]["base_uri"]
        api_path = config["connectors"]["paradex"]["rest"]["api_path"]
        self.__exchange_url_prefix = f"{base_uri}{api_path}"

    def __register_endpoints(self, server: WebServer) -> None:
        # TODO: Should ideally be a GET request.
        server.register("POST", "/private/exchange-token", self.__get_jwt)
        server.register("POST", "/private/order-signature", self.__sign_order_request)

        # Endpoints for TTS
        server.register("GET", "/private/get-l2-balance", self.__get_l2_balance)
        server.register("GET", "/private/get-socialized-loss-factor", self.__get_socialized_loss_factor)

        server.register("POST", "/private/deposit-into-l2", self.__deposit_into_l2)
        server.register("POST", "/private/transfer-to-l2-trading", self.__transfer_to_l2_trading)

        server.register("POST", "/private/withdraw-from-l2", self.__withdraw_from_l2)
        server.register("POST", "/private/transfer-from-l1-bridge-to-wallet", self.__transfer_from_l1_bridge_to_wallet)

    async def start(self, eth_private_key: str):
        self.__pdex_config = PdexSystemConfig.from_json(await self.__get_exchange_config())
        self.__pdex_account = PdexAccount(eth_private_key, self.__pdex_config)
        await self.__pdex_account.onboard_account(self.__pdex_config, self.__exchange_url_prefix)

        await self._api.initialize(
            private_key_or_mnemonic=eth_private_key,
            paradex_account_address=self.__pdex_account.address,
            paradex_private_key=hex(self.__pdex_account.get_private_key())
        )

        await super().start(eth_private_key)

        self.__load_whitelist()

        await self.__gas_price_tracker.start()
        await self.__gas_price_tracker.wait_gas_price_ready()

        await self.__get_jwt_from_exchange()

        # Periodically refresh JWT from the exchange
        self.pantheon.spawn(self.__refresh_jwt(self.__exchange_token_refresh_interval_s))

        max_nonce_cached = self._request_cache.get_max_nonce()
        self._api.initialize_starting_nonce(max_nonce_cached + 1)

    def __load_whitelist(self):
        file_prefix = os.path.dirname(os.path.realpath(__file__))
        addresses_whitelists_file_path = f'{file_prefix}/../../resources/pdex_contracts_address.json'
        self._logger.debug(f'Loading addresses whitelists from {addresses_whitelists_file_path}')
        with open(addresses_whitelists_file_path, 'r') as contracts_address_file:
            contracts_address_json = json.load(contracts_address_file)[self.__chain_name]

            tokens_list_json = contracts_address_json["tokens"]
            tokens_list = []
            for token_json in tokens_list_json:
                symbol = token_json["symbol"]
                if symbol in self._withdrawal_address_whitelists:
                    raise RuntimeError(f'Duplicate token : {symbol} in contracts_address file')
                self._withdrawal_address_whitelists[symbol] = token_json["valid_withdrawal_addresses"]

                if symbol != self.__native_token:
                    tokens_list.append(ERC20Token(
                        token_json["symbol"], Web3.to_checksum_address(token_json["address"])))

    async def __get_jwt(self, *_) -> Tuple[int, dict]:
        # Periodicaly query the exchange for a new jwt token.
        # This token is stored and forwarded to clients in response to a request
        # for a token.
        if self.__jwt:
            response = 200, {
              "token": self.__jwt.value,
              "expiration": self.__jwt.expiration
            }
        else:
            response = 400, {"error": "Unable to refresh JWT"}

        return response

    async def __refresh_jwt(self, refresh_interval_s: int) -> None:
        while True:
            await self.pantheon.sleep(refresh_interval_s)
            self._logger.debug("Refreshing JWT from exchange")
            await self.__get_jwt_from_exchange()

    async def __get_jwt_from_exchange(self,) -> None:
        now = int(time.time())
        pdex_signature_expiry = now + 24 * 60 * 60
        msg = StarknetMessages.authentication(self.__pdex_config.starknet_chain_id, now, pdex_signature_expiry)
        msg_hash = self.__pdex_account.hash_msg(msg)
        msg_signature = self.__pdex_account.sign_msg(msg)

        headers = {
            "PARADEX-STARKNET-ACCOUNT": self.__pdex_account.address,
            "PARADEX-STARKNET-SIGNATURE": msg_signature,
            "PARADEX-STARKNET-MESSAGE-HASH": hex(msg_hash),
            "PARADEX-TIMESTAMP": str(now),
            "PARADEX-SIGNATURE-EXPIRATION": str(pdex_signature_expiry),
        }

        url = f"{self.__exchange_url_prefix}/auth"

        try:
            async with aiohttp.ClientSession(json_serialize=ujson.dumps) as session:
                async with session.post(url, headers=headers) as response:
                    status_code = response.status
                    response = await response.json()

                    if status_code == 200:
                        self.__jwt = JWT.from_string(response["jwt_token"])
                    else:
                        self.__jwt = None
                        self._logger.error(f"Unable to refresh JWT. Exchange returned status_code({status_code}), error({response['error']}), details({response['message']})")
        except Exception as ex:
           self._logger.error(f"Unable to refresh JWT. Error[{str(ex)}]")

    def __assert_order_request_schema(self, received_keys: list) -> None:
        expected_keys = [
            "order_creation_ts_ms",
            "market",
            "side",
            "type",
            "size",
            "price"
        ]

        assert len(received_keys) == len(expected_keys), f"Request does not contain the correct set of fields. Expected [{', '.join(expected_keys)}]"
        for key in expected_keys: assert key in received_keys, f"Missing field({key}) in the request"

    async def __sign_order_request(
        self, path: str, params: dict, received_at_ms: int
    ) -> Tuple[int, dict]:
        try:
            self.__assert_order_request_schema(params.keys())

            msg = StarknetMessages.order_request(
                self.__pdex_config.starknet_chain_id,
                params["order_creation_ts_ms"],
                params["market"],
                params["side"],
                params["type"],
                params["size"],
                params["price"]
            )

            self._logger.debug(f"order request to sign => {msg}")
            msg_signature = await self.pantheon.loop.run_in_executor(
                self.__process_pool,
                self.__pdex_account.sign_msg,
                msg
            )
            self._logger.debug(f"order request signature => {msg_signature}")

            return 200, {"signature": msg_signature}
        except Exception as e:
            return 400, {"error": str(e)}

    async def __get_exchange_config(self) -> dict:
        try:
            payload = await self._api.get_system_config()
        except Exception as ex:
            raise Exception(f"Failed to query /system/config for setup. Error({str(ex)})")
        return payload

    async def __get_l2_balance(
        self,
        path: str,
        params: dict,
        received_at_ms: int
    ) -> Tuple[int, dict]:
        try:
            symbol = params["symbol"]
            balance = await self._api.get_l2_balance(symbol)
            return 200, {"balance": str(balance)}
        except Exception as e:
            return 400, {"error": {"message": repr(e)}}

    async def __get_socialized_loss_factor(
        self,
        path: str,
        params: dict,
        received_at_ms: int
    ) -> Tuple[int, dict]:
        try:
            socialized_loss_factor = await self._api.get_socialized_loss_factor()
            return 200, {"socialized_loss_factor": str(socialized_loss_factor)}
        except Exception as e:
            return 400, {"error": {"message": repr(e)}}

    # We don't need to do anything special on a new client connection
    async def on_new_connection(self, _):
        return

    async def process_request(self, ws, request_id: str, method: str, params: dict):
        return False

    def __mark_as_l2_request(self, request: Request) -> None:
        request.dex_specific = {"chain": "L2"}

    def __is_l2_request(self, request: Request) -> bool:
        return request.dex_specific and (request.dex_specific.get("chain", "") == "L2")

    async def _approve(
        self,
        symbol: str,
        amount: Decimal,
        gas_limit: int,
        gas_price_wei: int,
        nonce=None
    ):
        return await self._api.approve_deposit_into_l1_bridge(
            symbol, amount, gas_limit, gas_price_wei, nonce
        )

    async def _transfer(
         self,
         path: str,
         symbol: str,
         address_to: str,
         amount: str,
         gas_limit: int,
         gas_price_wei: int,
         nonce: int=None
    ):
        if path == '/private/withdraw':
            assert address_to is not None
            return await self._api.withdraw(symbol, address_to, amount, gas_limit, gas_price_wei)
        else:
            assert False

    async def _amend_transaction(self, request, params, gas_price_wei):
        if self.__is_l2_request(request):
            raise Exception("Amending L2 transactions is not supported")

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
        if self.__is_l2_request(request):
            raise Exception("Cancelling L2 transactions is not supported")

        if request.request_type == RequestType.ORDER or request.request_type == RequestType.TRANSFER or request.request_type == RequestType.APPROVE:
            return await self._api.cancel_transaction(request.nonce, gas_price_wei)
        else:
            raise Exception(f"Cancelling not supported for the {request.request_type}")

    async def get_transaction_receipt(self, request, tx_hash):
        if not self.__is_l2_request(request):
            return await self._api.get_transaction_receipt(tx_hash)
        else:
            receipt = await self._api.get_l2_transaction_receipt(tx_hash)
            if receipt.status in {TransactionStatus.ACCEPTED_ON_L2, TransactionStatus.ACCEPTED_ON_L1}:
                return {"status": 1}
            elif receipt.status == TransactionStatus.REJECTED:
                return {"status": 0}
            else:  # All other states map to "PENDING"
                return None

    def _get_gas_price(self, request, priority_fee: PriorityFee):
        return self.__gas_price_tracker.get_gas_price(priority_fee=priority_fee)

    async def on_request_status_update(self, client_request_id, request_status, tx_receipt: dict):
        await super().on_request_status_update(client_request_id, request_status, tx_receipt)

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
                # Only cancel L1 transactions
                if self.__is_l2_request(request): continue
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
        raise NotImplementedError('Method not implemented')

    async def __deposit_into_l2(
        self,
        path: str,
        params: dict,
        received_at_ms: int
    ):
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

            result = await self._api.deposit_into_l2(
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

    async def __transfer_to_l2_trading(
        self,
        path: str,
        params: dict,
        received_at_ms: int
    ):
        client_request_id = ''
        try:
            symbol = params['symbol']

            client_request_id = params['client_request_id']
            if self._request_cache.get(client_request_id) is not None:
                return 400, {'error': {'message': f'client_request_id={client_request_id} is already known'}}

            # The json deserializer for the type, TransferRequest, requires
            # amount to be a Decimal
            amount = 0

            if 'amount' in params:
                amount = Decimal(params['amount'])

            transfer = TransferRequest(
                client_request_id=client_request_id,
                symbol=symbol,
                amount=amount,
                # Leaving this empty as the `address_to` is hardcoded in the
                # pyutils api call and is our l2 account address
                address_to="",
                # Unused
                gas_limit=0,
                request_path=path,
                received_at_ms=received_at_ms)

            self.__mark_as_l2_request(transfer)

            self._logger.info(f"Transferring={transfer}, request_path={path}")

            self._request_cache.add(transfer)

            result = await self._api.transfer_to_l2_trading(symbol, amount)

            if result.error_type == ErrorType.NO_ERROR:
                transfer.nonce = result.nonce
                transfer.tx_hashes.append((result.tx_hash, RequestType.TRANSFER.name))
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

    async def __withdraw_from_l2(
        self,
        path: str,
        params: dict,
        received_at_ms: int
    ):
        client_request_id = ''
        try:
            symbol = params['symbol']

            client_request_id = params['client_request_id']
            if self._request_cache.get(client_request_id) is not None:
                return 400, {'error': {'message': f'client_request_id={client_request_id} is already known'}}

            amount = Decimal(params['amount'])

            transfer = TransferRequest(
                client_request_id=client_request_id,
                symbol=symbol,
                amount=amount,
                # Leaving this empty as the `address_to` is hardcoded in the
                # pyutils api call and is our L1 wallet address
                address_to="",
                # Unused
                gas_limit=0,
                request_path=path,
                received_at_ms=received_at_ms)

            self.__mark_as_l2_request(transfer)

            self._logger.debug(f"Transferring={transfer}, request_path={path}")

            self._request_cache.add(transfer)

            result = await self._api.withdraw_from_l2(symbol, amount)

            if result.error_type == ErrorType.NO_ERROR:
                transfer.nonce = result.nonce
                transfer.tx_hashes.append((result.tx_hash, RequestType.TRANSFER.name))
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

    async def __transfer_from_l1_bridge_to_wallet(
        self,
        path: str,
        params: dict,
        received_at_ms: int
    ):
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
                # pyutils api call and is our L1 wallet address
                address_to="",
                gas_limit=gas_limit,
                request_path=path,
                received_at_ms=received_at_ms)

            self._logger.info(f'Transferring={transfer}, request_path={path}, gas_price_wei={gas_price_wei}')

            self._request_cache.add(transfer)

            result = await self._api.transfer_from_l1_bridge_to_wallet(
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
