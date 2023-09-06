import asyncio
import base64
import json
import os
import time
import boto3

from collections import deque
from decimal import Decimal
from web3.exceptions import TransactionNotFound

from pantheon import Pantheon
from pantheon.instruments_source import InstrumentLifecycle, InstrumentUsageExchanges
from pantheon.market_data_types import InstrumentId, Side

from pyutils.exchange_apis.uniswapV3_api import *
from pyutils.exchange_connectors import ConnectorType

from ..dex_common import DexCommon


class UniswapV3Bloxroute(DexCommon):
    CHANNELS = ['ORDER']

    def __init__(self, pantheon: Pantheon, config, server, event_sink):
        super().__init__(pantheon, ConnectorType.UniswapV3, config, server, event_sink)

        self.msg_queue = asyncio.Queue()

        self._server.register(
            'POST', '/private/insert-order', self.__insert_order)

        self.__instruments = None
        self.__config = config
        self.__exchange_name = config['exchange_name']
        self.__chain_name = config['chain_name']
        self.__native_token = config['native_token']

        self.__next_targeted_block = 0
        self.__txs_in_next_targeted_block = []
        self.__tx_hash_with_targeted_block = deque()

    async def __insert_order(self, path, params: dict, received_at_ms):
        client_request_id = ''
        try:
            client_request_id = params['client_request_id']

            if self._request_cache.get(client_request_id) is not None:
                return 400, {'error': {'message': f'client_request_id={client_request_id} is already known'}}

            symbol = params['symbol']
            base_ccy_qty = Decimal(params['base_ccy_qty'])
            quote_ccy_qty = Decimal(params['quote_ccy_qty'])
            assert params['side'] == 'BUY' or params['side'] == 'SELL', 'Unknown order side'
            side = Side.BUY if params['side'] == 'BUY' else Side.SELL
            fee_rate = int(params['fee_rate'])
            gas_price_wei = int(params['gas_price_wei'])
            gas_limit = 210000  # TODO: Check for the most suitable value
            timeout_s = int(time.time() + params['timeout_s'])

            instrument = self.__instruments.get_instrument(
                InstrumentId(self.__exchange_name, symbol))
            base_ccy_symbol = instrument.base_currency
            quote_ccy_symbol = instrument.quote_currency

            order = OrderRequest(client_request_id, symbol, base_ccy_qty,
                                 quote_ccy_qty, side, fee_rate, gas_limit, timeout_s, received_at_ms)

            self._logger.debug(
                f'Inserting={order}, gas_price_wei={gas_price_wei}')
            self._request_cache.add(order)

            ok, reason = self._check_max_allowed_gas_price(gas_price_wei)
            if not ok:
                self._request_cache.finalise_request(
                    client_request_id, RequestStatus.FAILED)
                return 400, {'error': {'message': reason}}

            if not self._api.is_blx_mev_ws_ready():
                self._request_cache.finalise_request(
                    client_request_id, RequestStatus.FAILED)
                return 400, {'error': {'message': 'Bloxroute mev WS not ready'}}

            next_block_num = (await self._api.get_current_block_num()) + 1
            if (next_block_num > self.__next_targeted_block):
                self.__next_targeted_block = next_block_num
                self.__txs_in_next_targeted_block = []

            nonce = await self._api.get_total_txs_so_far() + len(self.__txs_in_next_targeted_block)

            if side == Side.BUY:
                built_tx = self._api.build_swap_exact_output_single_tx(
                    quote_ccy_symbol, base_ccy_symbol, quote_ccy_qty, base_ccy_qty, fee_rate, timeout_s,
                    gas_limit, gas_price_wei, nonce)
            else:
                built_tx = self._api.build_swap_exact_input_single_tx(
                    base_ccy_symbol, quote_ccy_symbol, base_ccy_qty, quote_ccy_qty, fee_rate, timeout_s,
                    gas_limit, gas_price_wei, nonce)

            signed_tx = self._api.sign_tx(built_tx)
            self.__txs_in_next_targeted_block.append(
                signed_tx.rawTransaction.hex()[2:])
            tx_hash = Web3.to_hex(signed_tx.hash)
            self.__tx_hash_with_targeted_block.append(
                (tx_hash, next_block_num))

            await self._api.send_bundle(self.__txs_in_next_targeted_block, self.__next_targeted_block)

            order.order_id = tx_hash
            order.nonce = nonce
            order.tx_hashes.append((tx_hash, RequestType.ORDER.name))
            order.used_gas_prices_wei.append(gas_price_wei)

            self._transactions_status_poller.add_for_polling(
                tx_hash, client_request_id, RequestType.ORDER)
            self._request_cache.add_or_update_request_in_redis(
                client_request_id)

            return 200, {'result': {'order_id': tx_hash, 'nonce': nonce}}

        except Exception as e:
            self._logger.exception(f'Failed to insert order: %r', e)
            self._request_cache.finalise_request(
                client_request_id, RequestStatus.FAILED)
            return 400, {'error': {'message': repr(e)}}

    async def _cancel_all(self, path, params, received_at_ms):
        return 400, {'error': {'message': repr(Exception('Cancel all request not supported by uni3 dex-proxy with '
                                                         'Bloxroute integrated'))}}

    async def _get_all_open_requests(self, path, params, received_at_ms):
        return await super()._get_all_open_requests(path, params, received_at_ms)

    async def on_new_connection(self, ws):
        return

    async def process_request(self, ws, request_id, method, params: dict):
        return False

    async def _approve(self, symbol, amount, gas_limit, gas_price_wei, nonce=None):
        if not self._api.is_blx_mev_ws_ready():
            return ApiResult(error_type=ErrorType.TRANSACTION_FAILED, error_message='Bloxroute mev WS not ready')

        next_block_num = (await self._api.get_current_block_num()) + 1
        if (next_block_num > self.__next_targeted_block):
            self.__next_targeted_block = next_block_num
            self.__txs_in_next_targeted_block = []

        nonce = await self._api.get_total_txs_so_far() + len(self.__txs_in_next_targeted_block)

        built_tx = self._api.build_approve_tx(
            symbol, amount, gas_limit, gas_price_wei, nonce)
        signed_tx = self._api.sign_tx(built_tx)
        self.__txs_in_next_targeted_block.append(
            signed_tx.rawTransaction.hex()[2:])
        tx_hash = Web3.to_hex(signed_tx.hash)
        self.__tx_hash_with_targeted_block.append((tx_hash, next_block_num))

        await self._api.send_bundle(self.__txs_in_next_targeted_block, self.__next_targeted_block)

        return ApiResult(nonce, tx_hash)

    async def _transfer(self, path, symbol, address_to, amount, gas_limit, gas_price_wei, nonce=None):
        if path == '/private/withdraw':
            assert address_to is not None

            if not self._api.is_blx_mev_ws_ready():
                return ApiResult(error_type=ErrorType.TRANSACTION_FAILED, error_message='Bloxroute mev WS not ready')

            next_block_num = (await self._api.get_current_block_num()) + 1
            if (next_block_num > self.__next_targeted_block):
                self.__next_targeted_block = next_block_num
                self.__txs_in_next_targeted_block = []

            nonce = await self._api.get_total_txs_so_far() + len(self.__txs_in_next_targeted_block)

            built_tx = self._api.build_withdraw_tx(
                symbol, address_to, amount, gas_limit, gas_price_wei, nonce)
            signed_tx = self._api.sign_tx(built_tx)
            self.__txs_in_next_targeted_block.append(
                signed_tx.rawTransaction.hex()[2:])
            tx_hash = Web3.to_hex(signed_tx.hash)
            self.__tx_hash_with_targeted_block.append(
                (tx_hash, next_block_num))

            await self._api.send_bundle(self.__txs_in_next_targeted_block, self.__next_targeted_block)

            return ApiResult(nonce, tx_hash)
        else:
            assert False

    async def _amend_transaction(self, request, params, gas_price_wei):
        raise Exception(
            'Amend request not supported by uni3 dex-proxy with Bloxroute integrated')

    async def _cancel_transaction(self, request, gas_price_wei):
        raise Exception(
            'Cancel request not supported by uni3 dex-proxy with Bloxroute integrated')

    async def get_transaction_receipt(self, request, tx_hash):
        return await self._api.get_transaction_receipt(tx_hash)

    def _get_gas_price(self, request, priority_fee):
        raise Exception(
            'Gas Price Tracker not supported by uni3 dex-proxy with Bloxroute integrated')

    async def on_request_status_update(self, client_request_id, request_status, tx_receipt: dict):
        request = self.get_request(client_request_id)
        if (request == None):
            return

        if (request_status == RequestStatus.SUCCEEDED and request.request_type == RequestType.ORDER):
            await self.__compute_exec_price(request, tx_receipt)

        await super().on_request_status_update(client_request_id, request_status, tx_receipt)

        if request.request_type == RequestType.ORDER:
            event = {
                'jsonrpc': '2.0',
                'method': 'subscription',
                'params': {
                    'channel': 'ORDER',
                    'data': request.to_dict()
                }
            }

            await self._event_sink.on_event('ORDER', event)

    async def __get_tx_status_ws(self):
        self.pantheon.spawn(self.__get_mined_tx_hash())

        while True:
            try:
                self._logger.info(
                    "[WS] Subscribing to get WS update for all mined transaction for the wallet")
                await self._api.subscribe_alchemy_mined_transactions(self.msg_queue)
                await self._api.get_public_websocket_status().wait_until_disconnected()
                await self._api.get_public_websocket_status().wait_until_connected()
            except Exception as e:
                self._logger.exception(
                    f'Error occurred in alchemy_mined_transactions ws subscription: %r', e)
                await self.pantheon.sleep(2)

    async def __get_mined_tx_hash(self):
        while True:
            try:
                message = await self.msg_queue.get()
                self._logger.info("[WS] [MESSAGE] %s", message)

                tx_hash = message['params']['result']['transaction']['hash']
                await self._transactions_status_poller.poll_for_status(tx_hash)
            except Exception as e:
                self._logger.exception(
                    f'Error occurred while handling WS message: %r', e)

    async def __compute_exec_price(self, request: OrderRequest, tx_receipt: dict):
        try:
            for log in tx_receipt['logs']:
                topic = Web3.to_hex(log['topics'][0])

                # 0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67 is the topic for the Swap event
                if topic == '0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67':
                    swap_log = self._api.get_swap_log(
                        log['address'], tx_receipt)
                    self._logger.debug(f'Swap_log={swap_log}')
                    # Sample swap_log:
                    # (AttributeDict({'args': AttributeDict({'sender': '0xE592427A0AEce92De3Edee1F18E0157C05861564',
                    # 'recipient': '0x03CdE1E0bc6C1e096505253b310Cf454b0b462FB', 'amount0': 100000000000, 'amount1': -332504806775,
                    # 'sqrtPriceX96': 144687485274156549416468062839, 'liquidity': 580197578039432673188, 'tick': 12045}),
                    # 'event': 'Swap', 'logIndex': 222, 'transactionIndex': 120, 'transactionHash':
                    # HexBytes('0x858c864355ca60d342c2b250ed4d641d66f4a922039ce4d2307101d75d5450eb'),
                    # 'address': '0x03AfDFB6CaBd6BA2a9e54015226F67E9295a9Bea', 'blockHash':
                    # HexBytes('0xdd5186fa2d0298777165467ddfcc944b073f68a9d1060b332c3fdfa7b5e90fbc'), 'blockNumber': 9065089}),)

                    instrument = self.__instruments.get_instrument(
                        InstrumentId(self.__exchange_name, request.symbol))
                    base_ccy_symbol = instrument.base_currency
                    quote_ccy_symbol = instrument.quote_currency

                    if (request.side == Side.BUY):
                        base_ccy_bought_amount = Decimal(self._api.from_native_amount(
                            base_ccy_symbol, abs(swap_log[0]['args']['amount0'])))
                        quote_ccy_sold_amount = Decimal(self._api.from_native_amount(
                            quote_ccy_symbol, abs(swap_log[0]['args']['amount1'])))
                        request.exec_price = quote_ccy_sold_amount/base_ccy_bought_amount
                    else:
                        base_ccy_sold_amount = Decimal(self._api.from_native_amount(
                            base_ccy_symbol, abs(swap_log[0]['args']['amount1'])))
                        quote_ccy_bought_amount = Decimal(self._api.from_native_amount(
                            quote_ccy_symbol, abs(swap_log[0]['args']['amount0'])))
                        request.exec_price = quote_ccy_bought_amount/base_ccy_sold_amount
        except Exception as ex:
            self._logger.exception(
                f'Error occurred while computing execution price of request={request}: %r', ex)

    # finalises requests who missed to get minned in the targeted block
    async def __finalise_missed_txs(self):
        while True:
            try:
                self._logger.debug(
                    'Polling for finalising txs missing targeted block')
                curr_block_num = await self._api.get_current_block_num()
                num_of_txs = len(self.__tx_hash_with_targeted_block)

                for i in range(0, num_of_txs):
                    try:
                        tx_hash, targeted_block = self.__tx_hash_with_targeted_block.popleft()
                        self._logger.debug(
                            f'tx_hash={tx_hash} targeted_block={targeted_block}')
                        if curr_block_num >= targeted_block:
                            receipt = await self.get_transaction_receipt(request=None, tx_hash=tx_hash)
                            if receipt is None:
                                # the current_block is >= than the targeted_block and receipt is None which means that
                                # the request has failed to get mined
                                self._transactions_status_poller.finalise(
                                    tx_hash, RequestStatus.FAILED)
                            # else:
                                # transaction_status_poller will handle finalising the request
                        else:
                            self.__tx_hash_with_targeted_block.appendleft(
                                (tx_hash, targeted_block))
                            break
                    except Exception as ex:
                        if isinstance(ex, TransactionNotFound):
                            # the current_block is >= than the targeted_block and receipt is not found which means that
                            # the request has failed to get mined
                            await self._transactions_status_poller.finalise(
                                tx_hash, RequestStatus.FAILED)
                        else:
                            # retry after 1 sec
                            self._logger.exception(
                                f'Error in polling tx_hash={tx_hash} targeted_block={targeted_block} for finalising txs missing targeted block: %r', ex)
                            self.__tx_hash_with_targeted_block.append(
                                (tx_hash, targeted_block))
            except Exception as e:
                self._logger.exception(
                    f'Error in polling for finalising txs missing targeted block: %r', e)
            await self.pantheon.sleep(1)

    def __get_blx_authorisation_header(self) -> str:
        if 'blx_authorisation_header' in self.__config:
            return self.__config['blx_authorisation_header']
        else:
            session = boto3.Session()
            client = session.client(service_name='secretsmanager')
            try:
                secret = client.get_secret_value(
                    SecretId=f'{self.pantheon.process_name}/3a5f7520d84c7b01d2a94f860d4202ba720')
                if 'SecretString' in secret:
                    auth_json = json.loads(secret['SecretString'])
                else:
                    decoded_binary_secret = base64.b64decode(secret['SecretBinary'])
                    auth_json = json.loads(decoded_binary_secret)
                return auth_json['auth_json']
            except Exception as ex:
                self._logger.exception(
                    f'Error in getting blx authorisation header: %r', ex)
                raise ex

    async def start(self, private_key):
        await super().start(private_key)

        self.__instruments = await self.pantheon.get_instruments_live_source(
            exchanges=[self.__exchange_name],
            symbols=[],
            kinds=[],
            usage=InstrumentUsageExchanges.TradableOnly,
            lifecycles=[InstrumentLifecycle.ACTIVE],
            rmq_conn_name='url')

        file_prefix = os.path.dirname(os.path.realpath(__file__))
        addresses_whitelists_file_path = f'{file_prefix}/../../resources/uni3_contracts_address.json'
        self._logger.debug(
            f'Loading addresses whitelists from {addresses_whitelists_file_path}')
        with open(addresses_whitelists_file_path, 'r') as contracts_address_file:
            contracts_address_json = json.load(contracts_address_file)[
                self.__chain_name]

            tokens_list_json = contracts_address_json["tokens"]
            tokens_list = []
            for token_json in tokens_list_json:
                symbol = token_json["symbol"]
                if symbol in self._withdrawal_address_whitelists:
                    raise RuntimeError(
                        f'Duplicate token : {symbol} in contracts_address file')
                self._withdrawal_address_whitelists[symbol] = token_json["valid_withdrawal_addresses"]

                if symbol != self.__native_token:
                    tokens_list.append(ERC20Token(
                        token_json["symbol"], Web3.to_checksum_address(token_json["address"])))

            uniswap_router_address = contracts_address_json["uniswap_router_address"]

        await self._api.initialize(private_key, uniswap_router_address, tokens_list)

        self.pantheon.spawn(self.__get_tx_status_ws())

        blx_authorisation_header = self.__get_blx_authorisation_header()
        await self._api.initialise_and_maintain_blx_mev_ws(blx_authorisation_header)

        self.pantheon.spawn(self.__finalise_missed_txs())
