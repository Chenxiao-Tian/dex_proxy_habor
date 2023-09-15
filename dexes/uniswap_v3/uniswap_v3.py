import asyncio
import json
import time
import os
from decimal import Decimal

from pantheon import Pantheon
from pantheon.market_data_types import Side
from pantheon.instruments_source import InstrumentLifecycle, InstrumentUsageExchanges
from pantheon.market_data_types import InstrumentId

from pyutils.exchange_apis.uniswapV3_api import *
from pyutils.exchange_apis.erc20web3_api import ErrorType
from pyutils.exchange_connectors import ConnectorType
from pyutils.gas_pricing.eth import GasPriceTracker, PriorityFee

from ..dex_common import DexCommon


class UniswapV3(DexCommon):
    CHANNELS = ['ORDER']

    def __init__(self, pantheon: Pantheon, config, server, event_sink):
        super().__init__(pantheon, ConnectorType.UniswapV3, config, server, event_sink)

        self.msg_queue = asyncio.Queue()

        self._server.register('POST', '/private/insert-order', self.__insert_order)

        self.__instruments = None
        self.__exchange_name = config['exchange_name']
        self.__chain_name = config['chain_name']
        self.__native_token = config['native_token']

        self.__gas_price_tracker = GasPriceTracker(pantheon, config['gas_price_tracker'])

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

            instrument = self.__instruments.get_instrument(InstrumentId(self.__exchange_name, symbol))
            base_ccy_symbol = instrument.base_currency
            quote_ccy_symbol = instrument.quote_currency

            ok, reason = self._check_max_allowed_gas_price(gas_price_wei)
            if not ok:
                return 400, {'error': {'message': reason}}

            order = OrderRequest(client_request_id, symbol, base_ccy_qty,
                                 quote_ccy_qty, side, fee_rate, gas_limit, timeout_s, received_at_ms)

            self._logger.debug(f'Inserting={order}, gas_price_wei={gas_price_wei}')
            self._request_cache.add(order)

            if side == Side.BUY:
                result = await self._api.swap_exact_output_single(
                    quote_ccy_symbol, base_ccy_symbol, quote_ccy_qty, base_ccy_qty, fee_rate, timeout_s,
                    gas_limit, gas_price_wei)
            else:
                result = await self._api.swap_exact_input_single(
                    base_ccy_symbol, quote_ccy_symbol, base_ccy_qty, quote_ccy_qty, fee_rate, timeout_s,
                    gas_limit, gas_price_wei)

            if result.error_type == ErrorType.NO_ERROR:
                order.order_id = result.tx_hash
                order.nonce = result.nonce
                order.tx_hashes.append((result.tx_hash, RequestType.ORDER.name))
                order.used_gas_prices_wei.append(gas_price_wei)

                self._transactions_status_poller.add_for_polling(result.tx_hash, client_request_id, RequestType.ORDER)
                self._request_cache.add_or_update_request_in_redis(client_request_id)

                return 200, {'result': {'order_id': result.tx_hash, 'nonce': result.nonce}}
            else:
                self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
                return 400, {'error': {'code': result.error_type.value, 'message': result.error_message}}

        except Exception as e:
            self._logger.exception(f'Failed to insert order: %r', e)
            self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
            return 400, {'error': {'message': repr(e)}}

    async def _cancel_all(self, path, params, received_at_ms):
        return await super()._cancel_all(path, params, received_at_ms)

    async def _get_all_open_requests(self, path, params, received_at_ms):
        return await super()._get_all_open_requests(path, params, received_at_ms)

    async def on_new_connection(self, ws):
        return

    async def process_request(self, ws, request_id, method, params: dict):
        return False

    async def _approve(self, symbol, amount, gas_limit, gas_price_wei, nonce=None):
        return await self._api.approve(symbol, amount, gas_limit, gas_price_wei, nonce)

    async def _transfer(self, path, symbol, address_to, amount, gas_limit, gas_price_wei, nonce=None):
        if path == '/private/withdraw':
            assert address_to is not None
            return await self._api.withdraw(symbol, address_to, amount, gas_limit, gas_price_wei)
        else:
            assert False

    async def _amend_transaction(self, request, params, gas_price_wei):
        if request.request_type == RequestType.ORDER:
            instrument = self.__instruments.get_instrument(InstrumentId(self.__exchange_name, request.symbol))
            base_ccy_symbol = instrument.base_currency
            quote_ccy_symbol = instrument.quote_currency

            timeout_s = int(time.time() + params['timeout_s'])
            request.deadline_since_epoch_s = timeout_s

            if request.side == Side.BUY:
                return await self._api.swap_exact_output_single(
                    quote_ccy_symbol, base_ccy_symbol, request.quote_ccy_qty, request.base_ccy_qty, request.fee_rate,
                    timeout_s, request.gas_limit, gas_price_wei, nonce=request.nonce)
            else:
                return await self._api.swap_exact_input_single(
                    base_ccy_symbol, quote_ccy_symbol, request.base_ccy_qty, request.quote_ccy_qty, request.fee_rate,
                    timeout_s, request.gas_limit, gas_price_wei, nonce=request.nonce)
        elif request.request_type == RequestType.TRANSFER:
            return await self._api.withdraw(
                request.symbol, request.address_to, request.amount, request.gas_limit, gas_price_wei,
                nonce=request.nonce)
        elif request.request_type == RequestType.APPROVE:
            return await self._api.approve(request.symbol, request.amount, request.gas_limit, gas_price_wei,
                                           nonce=request.nonce)
        else:
            raise Exception('Unsupported request type for amending')

    async def _cancel_transaction(self, request, gas_price_wei):
        if request.request_type == RequestType.ORDER or request.request_type == RequestType.TRANSFER or request.request_type == RequestType.APPROVE:
            return await self._api.cancel_transaction(request.nonce, gas_price_wei)
        else:
            raise Exception(f"Cancelling not supported for the {request.request_type}")

    async def get_transaction_receipt(self, request, tx_hash):
        return await self._api.get_transaction_receipt(tx_hash)

    def _get_gas_price(self, request, priority_fee: PriorityFee):
        return self.__gas_price_tracker.get_gas_price(priority_fee=priority_fee)

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
        self.pantheon.spawn(self.__receive_ws_messages())

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

    async def __receive_ws_messages(self):
        while True:
            try:
                message = await self.msg_queue.get()
                self._logger.info("[WS] [MESSAGE] %s", message)

                tx_hash = message['params']['result']['transaction']['hash']
                await self._transactions_status_poller.poll_for_status(tx_hash)
            except Exception as e:
                self._logger.exception(
                    f'Error occurred while handling WS message: %r', e)
                
    async def  __compute_exec_price(self, request: OrderRequest, tx_receipt: dict):
        try:
            for log in tx_receipt['logs']:
                topic = Web3.to_hex(log['topics'][0])
                
                # 0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67 is the topic for the Swap event
                if topic == '0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67':
                    swap_log = self._api.get_swap_log(log['address'], tx_receipt)
                    self._logger.debug(f'Swap_log={swap_log}')
                    # https://docs.uniswap.org/contracts/v3/reference/core/interfaces/pool/IUniswapV3PoolEvents#swap

                    # Sample swap_log:
                    # (AttributeDict({'args': AttributeDict({'sender': '0xE592427A0AEce92De3Edee1F18E0157C05861564',
                    # 'recipient': '0x03CdE1E0bc6C1e096505253b310Cf454b0b462FB', 'amount0': 100000000000, 'amount1': -332504806775,
                    # 'sqrtPriceX96': 144687485274156549416468062839, 'liquidity': 580197578039432673188, 'tick': 12045}),
                    # 'event': 'Swap', 'logIndex': 222, 'transactionIndex': 120, 'transactionHash':
                    # HexBytes('0x858c864355ca60d342c2b250ed4d641d66f4a922039ce4d2307101d75d5450eb'),
                    # 'address': '0x03AfDFB6CaBd6BA2a9e54015226F67E9295a9Bea', 'blockHash':
                    # HexBytes('0xdd5186fa2d0298777165467ddfcc944b073f68a9d1060b332c3fdfa7b5e90fbc'), 'blockNumber': 9065089}),)

                    # positive amount means that the corresponding token is added to the pool while negative amount means corresponding token is taken out of the pool

                    instrument = self.__instruments.get_instrument(
                        InstrumentId(self.__exchange_name, request.symbol))
                    base_ccy_symbol = instrument.base_currency
                    quote_ccy_symbol = instrument.quote_currency

                    token0_amount = Decimal(swap_log[0]['args']['amount0'])
                    token1_amount = Decimal(swap_log[0]['args']['amount1'])

                    if (request.side == Side.BUY):
                        if (token0_amount > 0):
                            base_ccy_amount = Decimal(
                                self._api.from_native_amount(base_ccy_symbol, abs(token1_amount)))
                            quote_ccy_amount = Decimal(
                                self._api.from_native_amount(quote_ccy_symbol, token0_amount))
                        else:
                            base_ccy_amount = Decimal(
                                self._api.from_native_amount(base_ccy_symbol, abs(token0_amount)))
                            quote_ccy_amount = Decimal(
                                self._api.from_native_amount(quote_ccy_symbol, token1_amount))
                    else:
                        if (token0_amount > 0):
                            base_ccy_amount = Decimal(
                                self._api.from_native_amount(base_ccy_symbol, token0_amount))
                            quote_ccy_amount = Decimal(
                                self._api.from_native_amount(quote_ccy_symbol, abs(token1_amount)))
                        else:
                            base_ccy_amount = Decimal(
                                self._api.from_native_amount(base_ccy_symbol, token1_amount))
                            quote_ccy_amount = Decimal(
                                self._api.from_native_amount(quote_ccy_symbol, abs(token0_amount)))

                    request.exec_price = round(
                        quote_ccy_amount/base_ccy_amount, 8).normalize()
        except Exception as ex:
            self._logger.exception(f'Error occurred while computing execution price of request={request}: %r', ex)

    async def start(self, private_key):
        await super().start(private_key)

        await self.__gas_price_tracker.start()
        await self.__gas_price_tracker.wait_gas_price_ready()

        self.__instruments = await self.pantheon.get_instruments_live_source(
            exchanges=[self.__exchange_name],
            symbols=[],
            kinds=[],
            usage=InstrumentUsageExchanges.TradableOnly,
            lifecycles=[InstrumentLifecycle.ACTIVE],
            rmq_conn_name='url')

        file_prefix = os.path.dirname(os.path.realpath(__file__))
        addresses_whitelists_file_path = f'{file_prefix}/../../resources/uni3_contracts_address.json'
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

            uniswap_router_address = contracts_address_json["uniswap_router_address"]

        await self._api.initialize(private_key, uniswap_router_address, tokens_list)

        max_nonce_loaded = self._request_cache.get_max_nonce()
        self._api.initialize_starting_nonce(max_nonce_loaded + 1)

        self.pantheon.spawn(self.__get_tx_status_ws())
