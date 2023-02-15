import asyncio
import json
import logging
import time

from decimal import Decimal

from pantheon import Pantheon
from pantheon.market_data_types import Side
from pantheon.instruments_source import InstrumentLifecycle, InstrumentUsageExchanges
from pantheon.market_data_types import InstrumentId

from pyutils.exchange_apis.uniswapV3_api import *
from pyutils.exchange_apis.erc20web3_api import ErrorType
from pyutils.exchange_apis import ApiFactory
from pyutils.exchange_connectors import ConnectorFactory, ConnectorType
from pyutils.gas_pricing.eth import GasPriceTracker, PriorityFee

from .requests_cache import RequestsCache
from .transactions_status_poller import TransactionsStatusPoller

_logger = logging.getLogger('uniswap_v3')


class UniswapV3:
    CHANNELS = ['ORDER']

    def __init__(self, pantheon: Pantheon, config, server, event_sink):
        self.pantheon = pantheon
        self.__server = server
        self.__event_sink = event_sink

        api_factory = ApiFactory(ConnectorFactory(config.get('connectors')))
        self.__api = api_factory.create(self.pantheon, ConnectorType.UniswapV3)

        self.__gas_price_tracker = GasPriceTracker(
            self.pantheon, config['gas_price_tracker'])

        self.msg_queue = asyncio.Queue()

        self.__tokens_to_valid_withdrawal_addresses = {}

        self.__server.register(
            'POST', '/private/insert-order', self.__insert_order)
        self.__server.register('POST', '/private/withdraw', self.__withdraw)
        self.__server.register(
            'POST', '/private/approve-token', self.__approve_token)
        self.__server.register(
            'GET', '/public/get-request-status', self.__get_request_status)
        self.__server.register(
            'GET', '/public/get-all-open-requests', self.__get_all_open_requests)
        self.__server.register(
            'POST', '/private/amend-request', self.__amend_request)
        self.__server.register(
            'DELETE', '/private/cancel-request', self.__cancel_request)
        self.__server.register(
            'DELETE', '/private/cancel-all', self.__cancel_all)
        self.__server.register(
            'GET', '/public/get-wallet-balance', self.__get_wallet_balance)

        self.__request_cache = RequestsCache(pantheon, self.__api, config['request_cache'])
        self.__transactions_status_poller = TransactionsStatusPoller(
            pantheon, self.__api, self.__request_cache, self.__on_request_status_update, config['transactions_status_poller'])

        self.__instruments = None

        self.__exchange_name = config['name']
        self.__chain_name = config['chain_name']
        self.__native_token = config['native_token']
        self.__max_allowed_gas_price_wei = config['max_allowed_gas_price_gwei'] * 10 ** 9

    async def process_request(self, ws, request_id, method, params: dict):
        return False

    async def __insert_order(self, params: dict):
        try:
            received_at_ms = int(time.time() * 1000)
            client_request_id = params['client_request_id']

            if (self.__request_cache.does_exist(client_request_id)):
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
            self.__request_cache.add(order)

            if (gas_price_wei > self.__max_allowed_gas_price_wei):
                self.__request_cache.finalise_request(
                    client_request_id, RequestStatus.FAILED)
                return 400, {'error': {'message': f'gas_price_wei={gas_price_wei} is greater than '
                                       f'max_allowed_gas_price_wei={self.__max_allowed_gas_price_wei}'}}

            _logger.debug(f'Inserting={order}, gas_price_wei={gas_price_wei}')

            if (side == Side.BUY):
                nonce, result = await self.__api.swap_exact_output_single(
                    quote_ccy_symbol, base_ccy_symbol, quote_ccy_qty, base_ccy_qty, fee_rate, timeout_s,
                    gas_limit, gas_price_wei)
            else:
                nonce, result = await self.__api.swap_exact_input_single(
                    base_ccy_symbol, quote_ccy_symbol, base_ccy_qty, quote_ccy_qty, fee_rate, timeout_s,
                    gas_limit, gas_price_wei)
            if result.error_type == ErrorType.NO_ERROR:
                order.order_id = result.tx_hash
                order.nonce = nonce
                self.__transactions_status_poller.add_for_polling(result.tx_hash, client_request_id, RequestType.ORDER)
                order.tx_hashes.append((result.tx_hash, RequestType.ORDER.name))
                order.used_gas_prices_wei.append(gas_price_wei)
                self.__request_cache.add_or_update_request_in_redis(
                    client_request_id)
                return 200, {'result': {'order_id': result.tx_hash, 'nonce': nonce}}
            else:
                self.__request_cache.finalise_request(
                    client_request_id, RequestStatus.FAILED)
                return 400, {'error': {'code': result.error_type.value, 'message': self.__api.get_error_description(result)}}
        except Exception as e:
            _logger.exception(f'Failed to insert order: %r', e)
            self.__request_cache.finalise_request(
                client_request_id, RequestStatus.FAILED)
            return 400, {'error': {'message': repr(e)}}

    async def __withdraw(self, params):
        try:
            received_at_ms = int(time.time() * 1000)
            client_request_id = params['client_request_id']

            if (self.__request_cache.does_exist(client_request_id)):
                return 400, {'error': {'message': f'client_request_id={client_request_id} is already known'}}

            symbol = params['symbol']
            amount = Decimal(params['amount'])
            gas_limit = int(params['gas_limit'])
            gas_price_wei = int(params['gas_price_wei'])
            address_to = params['address_to']

            transfer = TransferRequest(
                client_request_id, symbol, amount, address_to, gas_limit, received_at_ms)
            self.__request_cache.add(transfer)

            if (gas_price_wei > self.__max_allowed_gas_price_wei):
                self.__request_cache.finalise_request(
                    client_request_id, RequestStatus.FAILED)
                return 400, {'error': {'message': f'gas_price_wei={gas_price_wei} is greater than '
                                       f'max_allowed_gas_price_wei={self.__max_allowed_gas_price_wei}'}}

            if (symbol not in self.__tokens_to_valid_withdrawal_addresses):
                self.__request_cache.finalise_request(
                    client_request_id, RequestStatus.FAILED)
                _logger.error(
                    f'HIGH ALERT: client_request_id={client_request_id} tried to withdraw unknown symbol={symbol}')
                return 400, {'error': {'message': f'Unknown symbol={symbol}'}}

            if (address_to not in self.__tokens_to_valid_withdrawal_addresses[symbol]):
                self.__request_cache.finalise_request(
                    client_request_id, RequestStatus.FAILED)
                _logger.error(
                    f'HIGH ALERT: client_request_id={client_request_id} tried to withdraw symbol={symbol} '
                    f'to unknown address={address_to}')
                return 400, {'error': {'message': f'Unknown withdrawal_address={address_to} for symbol={symbol}'}}

            _logger.debug(
                f'Withdrawing={transfer}, gas_price_wei={gas_price_wei}')

            nonce, result = await self.__api.withdraw(
                symbol, address_to, amount, gas_limit, gas_price_wei)

            if result.error_type == ErrorType.NO_ERROR:
                transfer.nonce = nonce
                self.__transactions_status_poller.add_for_polling(
                    result.tx_hash, client_request_id, RequestType.TRANSFER)
                transfer.tx_hashes.append((result.tx_hash, RequestType.TRANSFER.name))
                transfer.used_gas_prices_wei.append(gas_price_wei)
                self.__request_cache.add_or_update_request_in_redis(
                    client_request_id)
                return 200, {'withdraw_tx_hash': result.tx_hash}
            else:
                self.__request_cache.finalise_request(
                    client_request_id, RequestStatus.FAILED)
                return 400, {'error': {'code': result.error_type.value, 'message': self.__api.get_error_description(result)}}
        except Exception as e:
            _logger.exception(f'Failed to withdraw: %r', e)
            self.__request_cache.finalise_request(
                client_request_id, RequestStatus.FAILED)
            return 400, {'error': {'message': str(e)}}

    async def __approve_token(self, params):
        try:
            received_at_ms = int(time.time() * 1000)
            client_request_id = params['client_request_id']

            if (self.__request_cache.does_exist(client_request_id)):
                return 400, {'error': {'message': f'client_request_id={client_request_id} is already known'}}

            symbol = params['symbol']
            amount = Decimal(params['amount'])
            gas_price_wei = int(params['gas_price_wei'])

            gas_limit = 100000  # TODO: Check for the most suitable value

            approve = ApproveRequest(
                client_request_id, symbol, amount, gas_limit, received_at_ms)
            self.__request_cache.add(approve)

            if (gas_price_wei > self.__max_allowed_gas_price_wei):
                self.__request_cache.finalise_request(
                    client_request_id, RequestStatus.FAILED)
                return 400, {'error': {'message': f'gas_price_wei={gas_price_wei} is greater than '
                                       f'max_allowed_gas_price_wei={self.__max_allowed_gas_price_wei}'}}

            _logger.debug(
                f'Approving={approve}, gas_price_wei={gas_price_wei}')

            nonce, result = await self.__api.approve(symbol, amount, gas_limit, gas_price_wei)

            if result.error_type == ErrorType.NO_ERROR:
                approve.nonce = nonce
                self.__transactions_status_poller.add_for_polling(
                    result.tx_hash, client_request_id, RequestType.APPROVE)
                approve.tx_hashes.append((result.tx_hash, RequestType.APPROVE.name))
                approve.used_gas_prices_wei.append(gas_price_wei)
                self.__request_cache.add_or_update_request_in_redis(
                    client_request_id)
                return 200, {'approve_tx_hash': result.tx_hash}
            else:
                self.__request_cache.finalise_request(
                    client_request_id, RequestStatus.FAILED)
                return 400, {'error': {'code': result.error_type.value, 'message': self.__api.get_error_description(result)}}
        except Exception as e:
            _logger.exception(f'Failed to approve: %r', e)
            self.__request_cache.finalise_request(
                client_request_id, RequestStatus.FAILED)
            return 400, {'error': {'message': str(e)}}

    async def __get_request_status(self, params):
        try:
            client_request_id = params['client_request_id']

            _logger.debug(
                f'Getting request: client_request_id={client_request_id}')

            request = self.__request_cache.get(client_request_id)
            if (request):
                return 200, request.to_dict()
            else:
                return 404, {'error': {'message': 'Request not found'}}
        except Exception as e:
            _logger.exception(f'Failed to get request: %r', e)
            return 400, {'error': {'message': str(e)}}

    async def __get_all_open_requests(self, params):
        try:
            assert params['request_type'] == 'ORDER' or params['request_type'] == 'TRANSFER' or \
                params['request_type'] == 'APPROVE', 'Unknown transaction type'
            request_type = RequestType[params['request_type']]

            _logger.debug(
                f'Getting all open requests: request_type={request_type.name}')

            open_requests = []

            for request in self.__request_cache.get_all(request_type):
                if (request.is_finalised()):
                    continue
                open_requests.append(request.to_dict())

            return 200, open_requests
        except Exception as e:
            _logger.exception(f'Failed to get all open requests: %r', e)
            return 400, {'error': {'message': str(e)}}

    async def __amend_request(self, params: dict):
        try:
            client_request_id = params['client_request_id']
            request = self.__request_cache.get(client_request_id)

            if (request):
                if (request.request_status != RequestStatus.PENDING):
                    return 400, {'error': {'message': f'Cannot amend. Request status={request.request_status.name}'}}

                gas_price_wei = int(params['gas_price_wei'])

                if (gas_price_wei > self.__max_allowed_gas_price_wei):
                    return 400, {'error': {'message': f'gas_price_wei={gas_price_wei} is greater than '
                                           f'max_allowed_gas_price_wei={self.__max_allowed_gas_price_wei}'}}

                if (request.request_type == RequestType.ORDER):
                    timeout_s = int(time.time() + params['timeout_s'])

                    instrument = self.__instruments.get_instrument(
                        InstrumentId(self.__exchange_name, request.symbol))
                    base_ccy_symbol = instrument.base_currency
                    quote_ccy_symbol = instrument.quote_currency

                    request.deadline_since_epoch_s = timeout_s

                _logger.debug(
                    f'Amending={request}, gas_price_wei={gas_price_wei}')

                if (request.request_type == RequestType.ORDER):
                    if (request.side == Side.BUY):
                        _, result = await self.__api.swap_exact_output_single(
                            quote_ccy_symbol, base_ccy_symbol, request.quote_ccy_qty, request.base_ccy_qty, request.fee_rate,
                            timeout_s, request.gas_limit, gas_price_wei, nonce=request.nonce)
                    else:
                        _, result = await self.__api.swap_exact_input_single(
                            base_ccy_symbol, quote_ccy_symbol, request.base_ccy_qty, request.quote_ccy_qty, request.fee_rate,
                            timeout_s, request.gas_limit, gas_price_wei, nonce=request.nonce)
                elif (request.request_type == RequestType.TRANSFER):
                    _, result = await self.__api.withdraw(
                        request.symbol, request.address_to, request.amount, request.gas_limit, gas_price_wei,
                        nonce=request.nonce)
                else:
                    _, result = await self.__api.approve(request.symbol, request.amount, request.gas_limit, gas_price_wei,
                                                         nonce=request.nonce)

                if result.error_type == ErrorType.NO_ERROR:
                    request.tx_hashes.append((result.tx_hash, request.request_type.name))
                    request.used_gas_prices_wei.append(gas_price_wei)
                    self.__transactions_status_poller.add_for_polling(
                        result.tx_hash, client_request_id, request.request_type)
                    self.__request_cache.add_or_update_request_in_redis(
                        client_request_id)
                    if (request.request_type == RequestType.ORDER):
                        return 200, {'result': {'order_id': request.order_id}}
                    elif (request.request_type == RequestType.TRANSFER):
                        return 200, {'result': {'withdraw_amend_tx_hash': result.tx_hash}}
                    else:
                        return 200, {'result': {'approve_amend_tx_hash': result.tx_hash}}
                else:
                    return 400, {'error': {'code': result.error_type.value, 'message': self.__api.get_error_description(result)}}

            else:
                return 404, {'error': {'message': 'request not found'}}

        except Exception as e:
            _logger.exception(f'Failed to amend request: %r', e)
            return 400, {'error': {'message': repr(e)}}

    async def __cancel_request(self, params: dict):
        try:
            client_request_id = params['client_request_id']
            gas_price_wei = int(params.get('gas_price_wei', self.__gas_price_tracker.get_gas_price(
                priority_fee=PriorityFee.Fast)))
            request = self.__request_cache.get(client_request_id)

            if (request):
                if (request.is_finalised()):
                    return 400, {'error': {'message': f'Cannot cancel. Request status={request.request_status.name}'}}

                if ('gas_price_wei' not in params):

                    if (request.request_status == RequestStatus.CANCEL_REQUESTED and
                            request.used_gas_prices_wei[-1] >= gas_price_wei):
                        return 400, {'error': {'message': f'Cancel with greater than or equal to the '
                                               f'gas_price_wei={gas_price_wei} already in progress'}}

                    # replacement transaction should have gas_price atleast greater than 10% of the last gas_price used otherwise
                    # 'replacement transaction underpriced' error will occur. https://ethereum.stackexchange.com/a/44875
                    gas_price_wei = max(gas_price_wei, int(
                        1.1 * request.used_gas_prices_wei[-1]))

                if (gas_price_wei > self.__max_allowed_gas_price_wei):
                    return 400, {'error': {'message': f'gas_price_wei={gas_price_wei} is greater than '
                                           f'max_allowed_gas_price_wei={self.__max_allowed_gas_price_wei}'}}

                _logger.debug(
                    f'Canceling={request}, gas_price_wei={gas_price_wei}')

                _, result = self.__cancel_transaction(
                    gas_price_wei, nonce=request.nonce)

                if result.error_type == ErrorType.NO_ERROR:
                    request.request_status = RequestStatus.CANCEL_REQUESTED
                    self.__transactions_status_poller.add_for_polling(
                        result.tx_hash, client_request_id, RequestType.CANCEL)
                    request.tx_hashes.append((result.tx_hash, RequestType.CANCEL.name))
                    request.used_gas_prices_wei.append(gas_price_wei)
                    self.__request_cache.add_or_update_request_in_redis(
                        client_request_id)

                    if (request.request_type == RequestType.ORDER):
                        return 200, {'result': {'order_id': request.order_id}}
                    elif (request.request_type == RequestType.TRANSFER):
                        return 200, {'result': {'withdraw_cancel_tx_hash': result.tx_hash}}
                    else:
                        return 200, {'result': {'approve_cancel_tx_hash': result.tx_hash}}
                else:
                    return 400, {'error': {'code': result.error_type.value, 'message': self.__api.get_error_description(result)}}
            else:
                return 404, {'error': {'message': 'request not found'}}
        except Exception as e:
            _logger.exception(f'Failed to cancel request: %r', e)
            return 400, {'error': {'message': repr(e)}}

    async def __cancel_all(self, params):
        try:
            assert params['request_type'] == 'ORDER' or params['request_type'] == 'TRANSFER' \
                or params['request_type'] == 'APPROVE', 'Unknown transaction type'
            request_type = RequestType[params['request_type']]

            _logger.debug(
                f'Canceling all requests, request_type={request_type.name}')

            cancel_requested = []
            failed_cancels = []

            for request in self.__request_cache.get_all(request_type):
                if (request.is_finalised()):
                    continue

                gas_price_wei = self.__gas_price_tracker.get_gas_price(
                    priority_fee=PriorityFee.Fast)

                if (request.request_status == RequestStatus.CANCEL_REQUESTED and
                        request.used_gas_prices_wei[-1] >= gas_price_wei):
                    _logger.info(
                        f'Not sending cancel request for client_request_id={request.client_request_id} as cancel with '
                        f'greater than or equal to the gas_price_wei={gas_price_wei} already in progress')
                    cancel_requested.append(request.client_request_id)
                    continue

                gas_price_wei = max(gas_price_wei, int(
                    1.1 * request.used_gas_prices_wei[-1]))

                if (gas_price_wei > self.__max_allowed_gas_price_wei):
                    _logger.error(
                        f'Not sending cancel request for client_request_id={request.client_request_id} as gas_price_wei='
                        f'{gas_price_wei} is greater than max_allowed_gas_price_wei={self.__max_allowed_gas_price_wei}')
                    failed_cancels.append(request.client_request_id)
                    continue

                _logger.debug(
                    f'Canceling={request}, gas_price_wei={gas_price_wei}')

                _, result = self.__cancel_transaction(
                    gas_price_wei, nonce=request.nonce)

                if result.error_type == ErrorType.NO_ERROR:
                    request.request_status = RequestStatus.CANCEL_REQUESTED
                    request.tx_hashes.append((result.tx_hash, RequestType.CANCEL.name))
                    request.used_gas_prices_wei.append(gas_price_wei)
                    cancel_requested.append(request.client_request_id)
                    self.__transactions_status_poller.add_for_polling(
                        result.tx_hash, request.client_request_id, RequestType.CANCEL)
                    self.__request_cache.add_or_update_request_in_redis(
                        request.client_request_id)
                else:
                    failed_cancels.append(request.client_request_id)
            return 400 if failed_cancels else 200, {'cancel_requested': cancel_requested, 'failed_cancels': failed_cancels}
        except Exception as e:
            _logger.exception(f'Failed to cancel all: %r', e)
            return 400, {'error': {'message': str(e)}}

    async def __get_wallet_balance(self, params):
        try:
            symbol = params['symbol']
            _logger.debug(f'Getting exchange balance: symbol={symbol}')
            balance = await self.__api.get_wallet_balance(symbol)
            return 200, {'result': {symbol: balance}}
        except Exception as e:
            _logger.exception(f'Failed to get exchange balance: %r', e)
            return 400, {'error': {'message': str(e)}}

    def __cancel_transaction(self, gas_price_wei: int, nonce: int):
        _logger.debug(f'Trying to cancel transaction with nonce={nonce}')
        return self.__api.cancel_transaction(nonce, gas_price_wei)

    async def __get_tx_status_ws(self):
        self.pantheon.spawn(self.__receive_ws_messages())

        while True:
            try:
                _logger.info(
                    "[WS] Subscribing to get WS update for all mined transaction for the wallet")
                await self.__api.subscribe_alchemy_mined_transactions(self.msg_queue)
                await self.__api.get_public_websocket_status().wait_until_disconnected()
                await self.__api.get_public_websocket_status().wait_until_connected()
            except Exception as ex:
                _logger.exception(
                    f'Error occured in alchemy_mined_transactions ws subscription: %r', ex)
                await self.pantheon.sleep(2)

    async def __receive_ws_messages(self):
        while True:
            try:
                message = await self.msg_queue.get()
                _logger.info("[WS] [MESSAGE] %s", message)

                tx_hash = message['params']['result']['transaction']['hash']
                await self.__transactions_status_poller.poll_for_status(tx_hash)
            except Exception as ex:
                _logger.exception(
                    f'Error occured while handling WS message: %r', ex)

    async def __on_request_status_update(self, client_request_id):
        request = self.__request_cache.get(client_request_id)

        if (request and request.request_type == RequestType.ORDER):
            event = {
                'jsonrpc': '2.0',
                'method': 'subscription',
                'params': {
                    'channel': 'ORDER',
                    'data': request.to_dict()
                }
            }
            await self.__event_sink.on_event('ORDER', event)

    async def start(self, private_key):
        await self.__gas_price_tracker.start()

        self.__instruments = await self.pantheon.get_instruments_live_source(
            exchanges=[self.__exchange_name],
            symbols=[],
            kinds=[],
            usage=InstrumentUsageExchanges.TradableOnly,
            lifecycles=[InstrumentLifecycle.ACTIVE],
            rmq_conn_name='url')

        with open('./resources/contracts_address.json', 'r') as contracts_address_file:
            contracts_address_json = json.load(contracts_address_file)[
                self.__chain_name]

            tokens_list_json = contracts_address_json["tokens"]
            tokens_list = []
            for token_json in tokens_list_json:
                symbol = token_json["symbol"]
                if (symbol in self.__tokens_to_valid_withdrawal_addresses):
                    raise RuntimeError(
                        f'Duplicate token : {symbol} in contracts_address file')
                self.__tokens_to_valid_withdrawal_addresses[symbol] = token_json["valid_withdrawal_addresses"]

                if (symbol != self.__native_token):
                    tokens_list.append(ERC20Token(
                        token_json["symbol"], Web3.to_checksum_address(token_json["address"])))

            uniswap_router_address = contracts_address_json["uniswap_router_address"]

        await self.__api.initialize(private_key, uniswap_router_address, tokens_list)

        self.pantheon.spawn(self.__get_tx_status_ws())
        await self.__transactions_status_poller.start()
        await self.__request_cache.start(self.__transactions_status_poller)
        await self.__gas_price_tracker.wait_gas_price_ready()
