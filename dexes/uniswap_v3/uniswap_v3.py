import asyncio
import logging
import time

from decimal import Decimal
from enum import Enum

from pantheon import Pantheon
from pantheon.market_data_types import Side
from pantheon.instruments_source import InstrumentLifecycle, InstrumentUsageExchanges
from pantheon.market_data_types import InstrumentId

from pyutils.exchange_apis.uniswapV3_api import *
from pyutils.exchange_apis.erc20web3_api import ErrorType
from pyutils.exchange_apis import ApiFactory
from pyutils.exchange_connectors import ConnectorFactory, ConnectorType

from web3.exceptions import TransactionNotFound

_logger = logging.getLogger('uniswap_v3')


class RequestType(Enum):
    ORDER = 'order'
    TRANSFER = 'transfer'


class RequestStatus(Enum):
    PENDING = 'pending'
    CANCEL_REQUESTED = 'cancel_requested'
    CANCELED = 'canceled'
    SUCCEEDED = 'succeeded'
    FAILED = 'failed'


class Request:
    def __init__(self, request_type: RequestType, client_request_id: str):
        self.request_type = request_type
        self.request_status = RequestStatus.PENDING
        self.client_request_id = client_request_id
        self.nonce = None
        self.finalised_at = None

    def is_finalised(self):
        if (self.finalised_at):
            return True
        return False


class OrderRequest(Request):
    def __init__(self, client_request_id: str, symbol: str, base_ccy_qty: Decimal, quote_ccy_qty: Decimal, side: Side,
                 fee_rate: int, gas_limit: int, deadline_since_epoch_s: int):
        super().__init__(RequestType.ORDER, client_request_id)
        self.order_id = None
        self.symbol = symbol
        self.base_ccy_qty = base_ccy_qty
        self.quote_ccy_qty = quote_ccy_qty
        self.side = side
        self.fee_rate = fee_rate
        self.gas_limit = gas_limit
        self.deadline_since_epoch_s = deadline_since_epoch_s

    def __str__(self):
        return f'Order: order_id={self.order_id}, client_request_id={self.client_request_id}, symbol={self.symbol}, ' \
            f'base_ccy_qty={self.base_ccy_qty}, quote_ccy_qty={self.quote_ccy_qty}, side={self.side.name}, ' \
            f'fee_rate={self.fee_rate}, gas_limit={self.gas_limit}, request_status={self.request_status}, ' \
            f'request_type={self.request_type.name}, deadline_since_epoch_s={self.deadline_since_epoch_s}, ' \
            f'nonce={self.nonce}, finalised_at={self.finalised_at}'

    def to_dict(self):
        return {
            'order_id': self.order_id,
            'client_request_id': self.client_request_id,
            'symbol': self.symbol,
            'base_ccy_qty': str(self.base_ccy_qty),
            'quote_ccy_qty': str(self.quote_ccy_qty),
            'side': self.side.name,
            'fee_rate': self.fee_rate,
            'gas_limit': self.gas_limit,
            'nonce': self.nonce,
            'request_type': self.request_type.name,
            'request_status': self.request_status.name
        }


class TransferRequest(Request):
    def __init__(self, client_request_id: str, symbol: str, amount: Decimal, address_to, gas_limit: int):
        super().__init__(RequestType.TRANSFER, client_request_id)
        self.symbol = symbol
        self.amount = amount
        self.address_to = address_to
        self.gas_limit = gas_limit

    def __str__(self):
        return f'TransferRequest: client_request_id={self.client_request_id}, symbol={self.symbol}, amount={self.amount}, ' \
            f'address_to={self.address_to}, gas_limit={self.gas_limit}, request_status={self.request_status}, ' \
            f'request_type={self.request_type.name}, nonce={self.nonce}, finalised_at={self.finalised_at}'

    def to_dict(self):
        return {
            'client_request_id': self.client_request_id,
            'symbol': self.symbol,
            'amount': self.amount,
            'address_to': self.address_to,
            'gas_limit': self.gas_limit,
            'nonce': self.nonce,
            'request_type': self.request_type.name,
            'request_status': self.request_status.name
        }


class Uniswap:
    CHANNELS = ['ORDER']

    def __init__(self, pantheon: Pantheon, config, server, event_sink):
        self.pantheon = pantheon
        self.__config = config
        self.__server = server
        self.__event_sink = event_sink

        api_factory = ApiFactory(ConnectorFactory(config.get('connectors')))
        self.__api = api_factory.create(self.pantheon, ConnectorType.UniswapV3)

        self.msg_queue = asyncio.Queue(loop=self.pantheon.loop)

        self.__server.register(
            'POST', '/private/insert-order', self.__insert_order)
        self.__server.register('POST', '/private/withdraw', self.__withdraw)
        self.__server.register(
            'GET', '/public/get-request-status', self.__get_request_status)
        self.__server.register(
            'POST', '/private/amend-request', self.__amend_request)
        self.__server.register(
            'DELETE', '/private/cancel-request', self.__cancel_request)
        self.__server.register(
            'DELETE', '/private/cancel-all', self.__cancel_all)
        self.__server.register(
            'GET', '/public/get-wallet-balance', self.__get_wallet_balance)

        self.__requests = {}
        self.__swap_tx_hash_to_client_rid = {}
        self.__transfer_tx_hash_to_client_rid = {}
        self.__cancel_tx_hash_to_client_rid = {}

        self.__exchange_name = config['name']
        self.__instruments = None

        self.finalised_requests_cleanup_after_s = int(
            config['finalised_requests_cleanup_after_s'])

    async def process_request(self, ws, request_id, method, params: dict):
        return False

    async def __insert_order(self, params: dict):
        try:
            client_request_id = params['client_request_id']
            symbol = params['symbol']
            base_ccy_qty = Decimal(params['base_ccy_qty'])
            quote_ccy_qty = Decimal(params['quote_ccy_qty'])
            assert params['side'] == 'BUY' or params['side'] == 'SELL', 'Unknown order side'
            side = Side.BUY if params['side'] == 'BUY' else Side.SELL
            fee_rate = int(params['fee_rate'])
            gas_price = int(params['gas_price'])
            gas_limit = 210000  # TODO: Check for the most suitable value
            timeout_s = int(time.time() + params.get('timeout_s'))

            instrument = self.__instruments.get_instrument(
                InstrumentId(self.__exchange_name, symbol))
            base_ccy_symbol = instrument.base_currency
            quote_ccy_symbol = instrument.quote_currency

            order = OrderRequest(client_request_id, symbol, base_ccy_qty,
                                 quote_ccy_qty, side, fee_rate, gas_limit, timeout_s)
            self.__requests[client_request_id] = order

            _logger.debug(f'Inserting={order}, gas_price={gas_price}')

            if (side == Side.BUY):
                nonce, result = await self.__api.swap_exact_output_single(
                    quote_ccy_symbol, base_ccy_symbol, quote_ccy_qty, base_ccy_qty, fee_rate, timeout_s, gas_limit, gas_price)
            else:
                nonce, result = await self.__api.swap_exact_input_single(
                    base_ccy_symbol, quote_ccy_symbol, base_ccy_qty, quote_ccy_qty, fee_rate, timeout_s, gas_limit, gas_price)
            if result.error_type == ErrorType.NO_ERROR:
                order.order_id = result.tx_hash
                order.nonce = nonce
                self.__swap_tx_hash_to_client_rid[result.tx_hash] = client_request_id
                return 200, {'result': {'order_id': result.tx_hash, 'nonce': nonce}}
            else:
                order.request_status = RequestStatus.FAILED
                order.finalised_at = time.time()
                return 400, {'error': {'code': result.error_type.value, 'message': self.__api.get_error_description(result)}}
        except Exception as e:
            _logger.exception(f'Failed to insert order: %r', e)
            order.request_status = RequestStatus.FAILED
            order.finalised_at = time.time()
            return 400, {'error': {'message': repr(e)}}

    async def __withdraw(self, params):
        try:
            client_request_id = params['client_request_id']
            symbol = params['symbol']
            amount = Decimal(params['amount'])
            address_to = params['address_to']
            gas_limit = int(params['gas_limit'])
            gas_price = int(params['gas_price'])

            transfer = TransferRequest(
                client_request_id, symbol, amount, address_to, gas_limit)
            self.__requests[client_request_id] = transfer

            _logger.debug(f'Withdrawing={transfer}, gas_price={gas_price}')

            nonce, result = await self.__api.withdraw(
                symbol, address_to, amount, gas_limit, gas_price)

            if result.error_type == ErrorType.NO_ERROR:
                transfer.nonce = nonce
                self.__transfer_tx_hash_to_client_rid[result.tx_hash] = client_request_id
                return 200, {'withdraw_tx_hash': result.tx_hash}
            else:
                transfer.request_status = RequestStatus.FAILED
                transfer.finalised_at = time.time()
                return 400, {'error': {'code': result.error_type.value, 'message': self.__api.get_error_description(result)}}
        except Exception as e:
            _logger.exception(f'Failed to withdraw: %r', e)
            transfer.request_status = RequestStatus.FAILED
            transfer.finalised_at = time.time()
            return 400, {'error': {'message': str(e)}}

    async def __get_request_status(self, params):
        try:
            client_request_id = params['client_request_id']

            _logger.debug(
                f'Getting request: client_request_id={client_request_id}')

            if (client_request_id in self.__requests.keys()):
                return 200, self.__requests[client_request_id].to_dict()
            else:
                return 404, {'error': {'message': 'Request not found'}}
        except Exception as e:
            _logger.exception(f'Failed to get request: %r', e)
            return 400, {'error': {'message': str(e)}}

    async def __amend_request(self, params: dict):
        try:
            client_request_id = params['client_request_id']

            if (client_request_id in self.__requests.keys()):
                request = self.__requests[client_request_id]

                if (request.request_status != RequestStatus.PENDING):
                    return 400, {'error': {'message': f'Cannot amend. Request status={request.request_status.name}'}}

                gas_price = int(params['gas_price'])

                if (request.request_type == RequestType.ORDER):
                    timeout_s = int(time.time() + params.get('timeout_s'))

                    instrument = self.__instruments.get_instrument(
                        InstrumentId(self.__exchange_name, request.symbol))
                    base_ccy_symbol = instrument.base_currency
                    quote_ccy_symbol = instrument.quote_currency

                    request.deadline_since_epoch_s = timeout_s

                _logger.debug(f'Amending={request}, gas_price={gas_price}')

                if (request.request_type == RequestType.ORDER):
                    if (request.side == Side.BUY):
                        _, result = await self.__api.swap_exact_output_single(
                            quote_ccy_symbol, base_ccy_symbol, request.quote_ccy_qty, request.base_ccy_qty, request.fee_rate,
                            timeout_s, request.gas_limit, gas_price, nonce=request.nonce)
                    else:
                        _, result = await self.__api.swap_exact_input_single(
                            base_ccy_symbol, quote_ccy_symbol, request.base_ccy_qty, request.quote_ccy_qty, request.fee_rate,
                            timeout_s, request.gas_limit, gas_price, nonce=request.nonce)
                else:
                    _, result = await self.__api.withdraw(
                        request.symbol, request.address_to, request.amount, request.gas_limit, gas_price,
                        nonce=request.nonce)

                if result.error_type == ErrorType.NO_ERROR:
                    if (request.request_type == RequestType.ORDER):
                        self.__swap_tx_hash_to_client_rid[result.tx_hash] = client_request_id
                        return 200, {'result': {'order_id': request.order_id}}
                    else:
                        self.__transfer_tx_hash_to_client_rid[result.tx_hash] = client_request_id
                        return 200, {'result': {'withdraw_amend_tx_hash': result.tx_hash}}
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
            gas_price = int(params['gas_price'])

            if (client_request_id in self.__requests.keys()):
                request = self.__requests[client_request_id]

                if (request.is_finalised()):
                    return 400, {'error': {'message': f'Cannot cancel. Request status={request.request_status.name}'}}

                _logger.debug(f'Canceling={request}, gas_price={gas_price}')

                _, result = self.__cancel_transaction(
                    gas_price, nonce=request.nonce)

                if result.error_type == ErrorType.NO_ERROR:
                    request.request_status = RequestStatus.CANCEL_REQUESTED
                    self.__cancel_tx_hash_to_client_rid[result.tx_hash] = client_request_id

                    if (request.request_type == RequestType.ORDER):
                        return 200, {'result': {'order_id': request.order_id}}
                    else:
                        return 200, {'result': {'withdraw_cancel_tx_hash': result.tx_hash}}
                else:
                    return 400, {'error': {'code': result.error_type.value, 'message': self.__api.get_error_description(result)}}
            else:
                return 404, {'error': {'message': 'request not found'}}
        except Exception as e:
            _logger.exception(f'Failed to cancel request: %r', e)
            return 400, {'error': {'message': repr(e)}}

    async def __cancel_all(self, params):
        try:
            _logger.debug('Canceling all orders')

            assert params['request_type'] == 'ORDER' or params['request_type'] == 'TRANSFER', 'Unknown transaction type'
            request_type = RequestType.ORDER if params['request_type'] == 'ORDER' else RequestType.TRANSFER

            cancel_requested = []
            failed_cancels = []

            for request in self.__requests.values():
                if (request.is_finalised() or request.request_type != request_type):
                    continue
                gas_price = 100
                _logger.debug(f'Canceling={request}, gas_price={gas_price}')

                _, result = self.__cancel_transaction(gas_price, nonce=request.nonce)

                if result.error_type == ErrorType.NO_ERROR:
                    request.request_status = RequestStatus.CANCEL_REQUESTED
                    cancel_requested.append(request.client_request_id)
                    self.__cancel_tx_hash_to_client_rid[result.tx_hash] = request.client_request_id
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

    def __cancel_transaction(self, gas_price: int, nonce: int):
        _logger.debug(f'Trying to cancel transaction with nonce={nonce}')
        return self.__api.cancel_transaction(nonce, gas_price)

    async def __poll_tx_for_status_rest(self, poll_interval_s):
        _logger.debug(
            f'Start polling for transaction status every {poll_interval_s}s')

        while True:
            _logger.debug('Polling status for swap transactions')
            await self.__poll_tx(self.__swap_tx_hash_to_client_rid, 'swap')

            _logger.debug('Polling status for transfer transactions')
            await self.__poll_tx(self.__transfer_tx_hash_to_client_rid, 'transfer')

            _logger.debug('Polling status for cancel transactions')
            await self.__poll_tx(self.__cancel_tx_hash_to_client_rid, 'cancel')

            await self.pantheon.sleep(poll_interval_s)

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
                await self.pantheon.sleep(2)

    async def __finalised_requests_cleanup(self, poll_interval_s):
        _logger.debug(
            f'Start polling for removing {self.finalised_requests_cleanup_after_s}s earlier finalised requests every {poll_interval_s}s')

        while True:
            for request in list(self.__requests.values()):
                if (request.is_finalised() and request.finalised_at + self.finalised_requests_cleanup_after_s < int(time.time())):
                    self.__requests.pop(request.client_request_id)

            await self.pantheon.sleep(poll_interval_s)

    async def __poll_tx(self, tx_hash_to_client_r_id: dict, tx_type: str):
        for tx_hash in list(tx_hash_to_client_r_id.keys()):
            client_request_id = tx_hash_to_client_r_id[tx_hash]
            if (client_request_id not in self.__requests):
                tx_hash_to_client_r_id.pop(tx_hash)
                continue
            request = self.__requests[client_request_id]
            if (request.is_finalised()):
                tx_hash_to_client_r_id.pop(tx_hash)
            else:
                try:
                    tx = self.__api.get_transaction_receipt(tx_hash)
                    if (tx is not None):
                        status = tx['status']
                        request.finalised_at = time.time()
                        if (tx_type == 'swap' or tx_type == 'transfer'):
                            if (status == 1):
                                request.request_status = RequestStatus.SUCCEEDED
                            else:
                                request.request_status = RequestStatus.FAILED
                        else:
                            request.request_status = RequestStatus.CANCELED

                        if (request.request_type == RequestType.ORDER):
                            event = {
                                'jsonrpc': '2.0',
                                'method': 'subscription',
                                'params': {
                                    'channel': 'ORDER',
                                    'data': request.to_dict()
                                }
                            }
                            await self.__event_sink.on_event('ORDER', event)
                except Exception as ex:
                    if not isinstance(ex, TransactionNotFound):
                        _logger.error(
                            f'Error polling tx_hash : {tx_hash} for client_request_id={client_request_id}, tx_type={tx_type}. Error={ex}')

    async def __receive_ws_messages(self):
        while True:
            try:
                message = await self.msg_queue.get()
                _logger.info("[WS] [MESSAGE] %s", message)

                tx_hash = message['params']['result']['transaction']['hash']
                await self.__update_request_status(tx_hash)
            except Exception as ex:
                _logger.error(f'Error occured while handling WS message {ex}')

    async def __update_request_status(self, tx_hash: str):
        if (tx_hash in self.__swap_tx_hash_to_client_rid):
            await self.__poll_tx(
                {tx_hash: self.__swap_tx_hash_to_client_rid[tx_hash]}, 'swap')
        elif (tx_hash in self.__transfer_tx_hash_to_client_rid):
            await self.__poll_tx(
                {tx_hash: self.__transfer_tx_hash_to_client_rid[tx_hash]}, 'transfer')
        elif (tx_hash in self.__cancel_tx_hash_to_client_rid):
            await self.__poll_tx(
                {tx_hash: self.__cancel_tx_hash_to_client_rid[tx_hash]}, 'cancel')
        else:
            _logger.error(f'No request found for the tx_hash={tx_hash}')

    async def start(self, private_key, secrets):
        self.__instruments = await self.pantheon.get_instruments_live_source(
            exchanges=[self.__exchange_name],
            symbols=[],
            kinds=[],
            usage=InstrumentUsageExchanges.TradableOnly,
            lifecycles=[InstrumentLifecycle.ACTIVE],
            rmq_conn_name='url')

        await self.__api.initialize(private_key)

        poll_interval_s = self.__config['poll_interval_s']
        self.pantheon.spawn(self.__get_tx_status_ws())
        self.pantheon.spawn(self.__poll_tx_for_status_rest(poll_interval_s))
        self.pantheon.spawn(self.__finalised_requests_cleanup(poll_interval_s))
