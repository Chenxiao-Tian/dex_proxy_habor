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


class TransactionType(Enum):
    SWAP = 'swap'
    CANCEL = 'cancel'
    TRANSFER = 'transfer'


class TransactionStatus(Enum):
    PENDING = 'pending'
    CANCEL_REQUESTED = 'cancel_requested'
    CANCELED = 'canceled'
    SUCCEEDED = 'succeeded'
    FAILED = 'failed'


class Order:
    def __init__(self, client_order_id: str, symbol: str, base_ccy_qty: Decimal, quote_ccy_qty: Decimal, side: Side,
                 fee_rate: int, deadline_since_epoch_s: int):
        self.order_id = None
        self.client_order_id = client_order_id
        self.symbol = symbol
        self.base_ccy_qty = base_ccy_qty
        self.quote_ccy_qty = quote_ccy_qty
        self.side = side
        self.fee_rate = fee_rate
        self.status = TransactionStatus.PENDING
        self.deadline_since_epoch_s = deadline_since_epoch_s,
        self.finalised_at = None

    def __str__(self):
        return f'Order: order_id={self.order_id}, client_order_id={self.client_order_id}, symbol={self.symbol}, ' \
            f'base_ccy_qty={self.base_ccy_qty}, quote_ccy_qty={self.quote_ccy_qty}, side={self.side.name}, ' \
            f'fee_rate={self.fee_rate}, status={self.status}, deadline_since_epoch_s={self.deadline_since_epoch_s}, ' \
            f'finalised_at={self.finalised_at}'

    def to_dict(self):
        return {
            'order_id': self.order_id,
            'client_order_id': self.client_order_id,
            'symbol': self.symbol,
            'base_ccy_qty': str(self.base_ccy_qty),
            'quote_ccy_qty': str(self.quote_ccy_qty),
            'side': self.side.name,
            'fee_rate': self.fee_rate,
            'status': self.status.name
        }

    def is_finalised(self):
        if (self.finalised_at):
            return True
        return False


class Uniswap:
    def __init__(self, pantheon: Pantheon, config, server, event_sink):
        self.pantheon = pantheon
        self.__config = config
        self.__server = server
        self.__event_sink = event_sink

        api_factory = ApiFactory(ConnectorFactory(config.get('connectors')))
        self.__api = api_factory.create(self.pantheon, ConnectorType.UniswapV3)

        self.__server.register('GET', '/public/get-order', self.__get_order)
        self.__server.register(
            'GET', '/public/get-wallet-balance', self.__get_wallet_balance)
        self.__server.register('POST', '/private/withdraw', self.__withdraw)
        self.__server.register(
            'POST', '/private/insert-order', self.__insert_order)
        self.__server.register(
            'POST', '/private/amend-order', self.__amend_order)
        self.__server.register(
            'DELETE', '/private/cancel-order', self.__cancel_order)
        self.__server.register(
            'DELETE', '/private/cancel-all', self.__cancel_all)

        self.__orders = {}
        self.__client_oid_to_nonce = {}
        self.__swap_tx_hash_to_client_oid = {}
        self.__cancel_tx_hash_to_client_oid = {}

        self.__instruments = None

        self.finalised_orders_cleanup_after_s = int(
            config['finalised_orders_cleanup_after_s'])

    async def process_request(self, ws, request_id, method, params: dict):
        return False

    async def __insert_order(self, params: dict):
        try:
            client_order_id = params['client_order_id']
            symbol = params['symbol']
            base_ccy_qty = Decimal(params['base_ccy_qty'])
            quote_ccy_qty = Decimal(params['quote_ccy_qty'])
            assert params['side'] == 'BUY' or params['side'] == 'SELL', 'Unknown order side'
            side = Side.BUY if params['side'] == 'BUY' else Side.SELL
            fee_rate = Decimal(params['fee_rate'])
            gas_price = int(params['gas_price'])
            timeout_s = int(time.time() + params.get('timeout_s'))

            instrument = self.__instruments.get_instrument(
                InstrumentId('uni3', symbol))
            base_ccy_symbol = instrument.base_currency
            quote_ccy_symbol = instrument.quote_currency

            order = Order(client_order_id, symbol, base_ccy_qty,
                          quote_ccy_qty, side, fee_rate, timeout_s)
            self.__orders[client_order_id] = order

            _logger.debug(f'Inserting : {order}')

            if (side == Side.BUY):
                nonce, result = self.__api.swap_exact_output_single(
                    quote_ccy_symbol, base_ccy_symbol, quote_ccy_qty, base_ccy_qty, fee_rate, timeout_s, 210000, gas_price)
            else:
                nonce, result = self.__api.swap_exact_input_single(
                    base_ccy_symbol, quote_ccy_symbol, base_ccy_qty, quote_ccy_qty, fee_rate, timeout_s, 210000, gas_price)
            if result.error_type == ErrorType.NO_ERROR:
                order.order_id = result.tx_hash
                self.__client_oid_to_nonce[client_order_id] = nonce
                self.__swap_tx_hash_to_client_oid[result.tx_hash] = client_order_id
                return 200, {'result': {'order_id': result.tx_hash}}
            else:
                order.status = TransactionStatus.FAILED
                order.finalised_at = time.time()
                return 400, {'error': {'code': result.error_type.value, 'message': self.__api.get_error_description(result)}}
        except Exception as e:
            _logger.exception(f'Failed to insert order: %r', e)
            order.status = TransactionStatus.FAILED
            order.finalised_at = time.time()
            return 400, {'error': {'message': repr(e)}}

    async def __amend_order(self, params: dict):
        try:
            client_order_id = params['client_order_id']

            if (client_order_id in self.__orders.keys()):
                order = self.__orders[client_order_id]

                if (order.status != TransactionStatus.PENDING):
                    return 400, {'error': {'message': f'Cannot amend. Order status={order.status.name}'}}

                gas_price = int(params['gas_price'])
                timeout_s = int(time.time() + params.get('timeout_s'))

                instrument = self.__instruments.get_instrument(
                    InstrumentId('uni3', order.symbol))
                base_ccy_symbol = instrument.base_currency
                quote_ccy_symbol = instrument.quote_currency

                order.deadline_since_epoch_s = timeout_s

                _logger.debug(f'Amending : {order}')

                if (order.side == Side.BUY):
                    _, result = self.__api.swap_exact_output_single(
                        quote_ccy_symbol, base_ccy_symbol, order.quote_ccy_qty, order.base_ccy_qty, order.fee_rate,
                        timeout_s, 210000, gas_price, nonce=self.__client_oid_to_nonce[client_order_id])
                else:
                    _, result = self.__api.swap_exact_input_single(
                        base_ccy_symbol, quote_ccy_symbol, order.base_ccy_qty, order.quote_ccy_qty, order.fee_rate,
                        timeout_s, 210000, gas_price, nonce=self.__client_oid_to_nonce[client_order_id])
                if result.error_type == ErrorType.NO_ERROR:
                    self.__swap_tx_hash_to_client_oid[result.tx_hash] = client_order_id
                    return 200, {'result': {'order_id': order.order_id}}
                else:
                    return 400, {'error': {'code': result.error_type.value, 'message': self.__api.get_error_description(result)}}

            else:
                return 404, {'error': {'message': 'order not found'}}

        except Exception as e:
            _logger.exception(f'Failed to amend order: %r', e)
            return 400, {'error': {'message': repr(e)}}

    async def __cancel_order(self, params: dict):
        try:
            client_order_id = params['client_order_id']
            gas_price = int(params['gas_price'])

            if (client_order_id in self.__orders.keys()):
                order = self.__orders[client_order_id]

                if (order.is_finalised()):
                    return 400, {'error': {'message': f'Cannot cancel. Order status={order.status.name}'}}

                _logger.debug(f'Canceling : {order}')

                _, result = self.cancel_transaction(
                    gas_price, nonce=self.__client_oid_to_nonce[client_order_id])

                if result.error_type == ErrorType.NO_ERROR:
                    order.status = TransactionStatus.CANCEL_REQUESTED
                    self.__cancel_tx_hash_to_client_oid[result.tx_hash] = client_order_id
                    return 200, {'result': {'order_id': order.order_id}}
                else:
                    return 400, {'error': {'code': result.error_type.value, 'message': self.__api.get_error_description(result)}}
            else:
                return 404, {'error': {'message': 'order not found'}}
        except Exception as e:
            _logger.exception(f'Failed to cancel order: %r', e)
            return 400, {'error': {'message': repr(e)}}

    async def __cancel_all(self, params):
        _logger.debug('Canceling all orders')

        cancel_requested = []
        failed_cancels = []

        for order in self.__orders.values():
            if (order.status == TransactionStatus.PENDING or order.status == TransactionStatus.CANCEL_REQUESTED):
                _logger.debug(f'Canceling : {order}')

                _, result = self.cancel_transaction(
                    1000000, nonce=self.__client_oid_to_nonce[order.client_order_id])

                if result.error_type == ErrorType.NO_ERROR:
                    order.status = TransactionStatus.CANCEL_REQUESTED
                    cancel_requested.append(order.client_order_id)
                    self.__cancel_tx_hash_to_client_oid[result.tx_hash] = order.client_order_id
                else:
                    failed_cancels.append(order.client_order_id)
        return 400 if failed_cancels else 200, {'cancel_requested': cancel_requested, 'failed_cancels': failed_cancels}

    async def __get_order(self, params):
        try:
            client_order_id = params['client_order_id']

            _logger.debug(f'Getting order: client_order_id={client_order_id}')

            if (client_order_id in self.__orders.keys()):
                return 200, self.__orders[client_order_id].to_dict()
            else:
                return 404, {'error': {'message': 'Order not found'}}
        except Exception as e:
            _logger.exception(f'Failed to get order: %r', e)
            return 400, {'error': {'message': str(e)}}

    async def __get_wallet_balance(self, params):
        try:
            symbol = params['symbol']
            _logger.debug(f'Getting exchange balance: symbol={symbol}')
            balance = self.__api.get_wallet_balance(symbol)
            return 200, {'result': {symbol: balance}}
        except Exception as e:
            _logger.exception(f'Failed to get exchange balance: %r', e)
            return 400, {'error': {'message': str(e)}}

    async def __withdraw(self, params):
        try:
            symbol = params['symbol']
            amount = Decimal(params['amount'])
            gas_price = int(params['gas_price'])

            _logger.debug(
                f'Withdrawing: symbol={symbol}, amount={amount}')

            _, result = self.__api.withdraw_token(
                symbol, amount, 210000, gas_price)

            if result.error_type == ErrorType.NO_ERROR:
                return 200, {'tx_hash': result.tx_hash}
            else:
                return 400, {'error': {'code': result.error_type.value, 'message': self.__api.get_error_description(result)}}
        except Exception as e:
            _logger.exception(f'Failed to withdraw: %r', e)
            return 400, {'error': {'message': str(e)}}

    async def __poll_tx_for_status(self, poll_interval_s):
        _logger.debug(
            f'Start polling for transaction status every {poll_interval_s}s')

        while True:
            _logger.debug('Polling status for swap transactions')
            await self.__poll_tx(self.__swap_tx_hash_to_client_oid,
                                 TransactionType.SWAP)

            _logger.debug('Polling status for cancel transactions')
            await self.__poll_tx(self.__cancel_tx_hash_to_client_oid,
                                 TransactionType.CANCEL)

            await self.pantheon.sleep(poll_interval_s)

    async def __finalised_order_cleanup(self, poll_interval_s):
        _logger.debug(
            f'Start polling for removing {self.finalised_orders_cleanup_after_s}s earlier finalised orders every {poll_interval_s}s')

        while True:
            for order in self.__orders.values():
                if (order.is_finalised() and order.finalised_at + self.finalised_orders_cleanup_after_s < int(time.time())):
                    self.__orders.pop(order.client_order_id)
                    self.__client_oid_to_nonce.pop(order.client_order_id)

            await self.pantheon.sleep(poll_interval_s)

    async def cancel_transaction(self, gas_price: int, nonce: int):
        _logger.debug(f'Trying to cancel transaction with nonce={nonce}')
        return self.__api.withdraw_native(0, gas_price, nonce)

    async def __poll_tx(self, tx_hash_to_clientOid: dict, type: TransactionType):
        channel = 'ORDER'
        for tx_hash in tx_hash_to_clientOid.keys():
            client_order_id = tx_hash_to_clientOid[tx_hash]
            if (client_order_id not in self.__orders):
                tx_hash_to_clientOid.pop(tx_hash)
                continue
            order = self.__orders[client_order_id]
            if (order.is_finalised()):
                tx_hash_to_clientOid.pop(tx_hash)
            else:
                try:
                    tx = self.__api.get_transaction_receipt(tx_hash)
                    if (not tx is None):
                        status = tx['status']
                        order.finalised_at = time.time()
                        if (type == TransactionType.SWAP):
                            if (status == 1):
                                order.status = TransactionStatus.SUCCEEDED
                            else:
                                order.status = TransactionStatus.FAILED
                        else:
                            order.status = TransactionStatus.CANCELED
                        event = {
                            'jsonrpc': '2.0',
                            'method': 'subscription',
                            'params': {
                                'channel': channel,
                                'data': order.to_dict()
                            }
                        }
                        await self.__event_sink.on_event(channel, event)
                except Exception as ex:
                    if not isinstance(ex, TransactionNotFound):
                        _logger.error(
                            f'Error polling tx_hash : {tx_hash} for order : {client_order_id}, transaction_type : {type.name}. ex = {ex}')

    async def start(self, private_key, secrets):
        self.__instruments = await self.pantheon.get_instruments_live_source(
            exchanges=[self.__config['name']],
            symbols=[],
            kinds=[],
            usage=InstrumentUsageExchanges.TradableOnly,
            lifecycles=[InstrumentLifecycle.ACTIVE],
            rmq_conn_name='url')

        await self.__api.initialize(private_key)

        poll_interval_s = self.__config['poll_interval_s']
        self.pantheon.spawn(self.__poll_tx_for_status(poll_interval_s))
        self.pantheon.spawn(self.__finalised_order_cleanup(poll_interval_s))
