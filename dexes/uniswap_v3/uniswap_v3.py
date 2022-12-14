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

_logger = logging.getLogger('uniswap_v3')


class Order:
    def __init__(self, client_oId: str, symbol: str, base_ccy_qty: Decimal, quote_ccy_qty: Decimal, side: Side, fee_rate: int, deadline_since_epoch_s: int):
        self.oId = None
        self.client_oId = client_oId
        self.symbol = symbol
        self.base_ccy_qty = base_ccy_qty
        self.quote_ccy_qty = quote_ccy_qty
        self.side = side
        self.fee_rate = fee_rate
        self.deadline_since_epoch_s = deadline_since_epoch_s
        self.cancel_requested = False
        self.finalised = False
        self.finalised_at = None
        self.reverted = False
        self.revert_reason = None

    def __str__(self):
        return f'Order: oid={self.oId}, client_oid={self.client_oId}, symbol={self.symbol}, ' \
               f'base_ccy_qty={self.base_ccy_qty}, quote_ccy_qty={self.quote_ccy_qty}, side={self.side.name}, ' \
               f'fee_rate={self.fee_rate}, cancel_requested={self.cancel_requested}, finalised={self.finalised}, ' \
               f'finalised_at={self.finalised_at}, reverted={self.reverted}, revert_reason={self.revert_reason}'

    def toDict(self):
        return {
            'oId': self.oId,
            'client_oId': self.client_oId,
            'symbol': self.symbol,
            'base_ccy_qty': str(self.base_ccy_qty),
            'quote_ccy_qty': str(self.quote_ccy_qty),
            'side': self.side.name,
            'fee_rate': self.fee_rate,
            'cancel_requested': self.cancel_requested,
            'finalised': self.finalised,
            'reverted': self.reverted,
            'revert_reason': self.revert_reason
        }


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

        self.__instruments = None

        self.finalised_orders_cleanup_after_s = int(
            config['finalised_orders_cleanup_after_s'])

    async def process_request(self, ws, request_id, method, params: dict):
        return False

    async def __insert_order(self, params: dict):
        try:
            client_oId = params['client_order_id']
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

            order = Order(client_oId, symbol, base_ccy_qty,
                          quote_ccy_qty, side, fee_rate, gas_price, timeout_s)
            self.__orders[client_oId] = order

            _logger.debug(f'Inserting : {order}')

            if (side == Side.BUY):
                nonce, result = self.__api.swap_exact_output_single(
                    quote_ccy_symbol, base_ccy_symbol, quote_ccy_qty, base_ccy_qty, fee_rate, timeout_s, 210000, gas_price)
            else:
                nonce, result = self.__api.swap_exact_input_single(
                    base_ccy_symbol, quote_ccy_symbol, base_ccy_qty, quote_ccy_qty, fee_rate, timeout_s, 210000, gas_price)
            if result.error_type == ErrorType.NO_ERROR:
                order.oId = result.tx_hash
                self.__client_oid_to_nonce[client_oId] = nonce
                return 200, {'result': {'order_id': result.tx_hash}}
            else:
                order.finalised = True
                order.reverted = True
                order.finalised_at = time.time()
                return 400, {'error': {'code': result.error_type.value, 'message': self.__api.get_error_description(result)}}
        except Exception as e:
            _logger.exception(f'Failed to insert order: %r', e)
            order.finalised = True
            order.reverted = True
            order.finalised_at = time.time()
            return 400, {'error': {'message': repr(e)}}

    async def __amend_order(self, params: dict):
        try:
            client_oId = params['client_order_id']

            if (client_oId in self.__orders.keys()):
                order = self.__orders[client_oId]

                if (order.finalised):
                    return 400, {'error': {'message': 'order already finalised'}}
                elif (order.cancel_requested):
                    return 400, {'error': {'message': 'Cannot amend. Cancel in progress'}}

                gas_price = int(params['gas_price'])
                timeout_s = int(time.time() + params.get('timeout_s'))

                instrument = self.__instruments.get_instrument(
                    InstrumentId('uni3', order.symbol))
                base_ccy_symbol = instrument.base_currency
                quote_ccy_symbol = instrument.quote_currency

                _logger.debug(f'Amending : {order}')

                if (order.side == Side.BUY):
                    _, result = self.__api.swap_exact_output_single(
                        quote_ccy_symbol, base_ccy_symbol, order.quote_ccy_qty, order.base_ccy_qty, order.fee_rate, timeout_s, 210000, gas_price, nonce=self.__client_oid_to_nonce[client_oId])
                else:
                    _, result = self.__api.swap_exact_input_single(
                        base_ccy_symbol, quote_ccy_symbol, order.base_ccy_qty, order.quote_ccy_qty, order.fee_rate, timeout_s, 210000, gas_price, nonce=self.__client_oid_to_nonce[client_oId])
                if result.error_type == ErrorType.NO_ERROR:
                    return 200, {'result': {'order_id': order.oId}}
                else:
                    return 400, {'error': {'code': result.error_type.value, 'message': self.__api.get_error_description(result)}}
                
            else:
                return 404, {'error': {'message': 'order not found'}}
            
        except Exception as e:
            _logger.exception(f'Failed to amend order: %r', e)
            return 400, {'error': {'message': repr(e)}}

    async def __cancel_order(self, params: dict):
        try:
            client_oId = params['client_order_id']
            gas_price = int(params['gas_price'])

            if (client_oId in self.__orders.keys()):
                order = self.__orders[client_oId]
                if (order.finalised):
                    return 400, {'error': {'message': 'order already finalised'}}
                _logger.debug(f'Canceling : {order}')
                _, result = self.__api.withdraw_native(
                    0, gas_price, nonce=self.__client_oid_to_nonce[client_oId])
                if result.error_type == ErrorType.NO_ERROR:
                    order.cancel_requested = True
                    return 200, {'result': {'order_id': order.oId}}
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
            if order.finalised == False and order.cancel_requested == False:
                _logger.debug(f'Canceling : {order}')
                _, result = self.__api.withdraw_native(
                    0, gas_price, nonce=self.__client_oid_to_nonce[order.client_oId])
                if result.error_type == ErrorType.NO_ERROR:
                    order.cancel_requested = True
                    cancel_requested.append(order.client_oId)
                else:
                    failed_cancels.append(order.client_oId)
        return 400 if failed_cancels else 200, {'cancel_requested': cancel_requested, 'failed_cancels': failed_cancels}

    async def __get_order(self, params):
        try:
            client_oId = params['client_order_id']
            _logger.debug(f'Getting order: client_oId={client_oId}')
            if (client_oId in self.__orders.keys()):
                return 200, self.__orders[client_oId].toDict()
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
            if result.error_type != ErrorType.NO_ERROR:
                return 400, {'error': {'code': result.error_type.value, 'message': self.__api.get_error_description(result)}}
            else:
                return 200, {'tx_hash': result.tx_hash}
        except Exception as e:
            _logger.exception(f'Failed to withdraw: %r', e)
            return 400, {'error': {'message': str(e)}}

    async def __poll_order_for_status(self, poll_interval_s):
        _logger.debug(
            f'Start polling for order status every {poll_interval_s}s')
        channel = 'ORDER'
        while True:
            async for order in self.__orders.values():
                if order.finalised == False:
                    # TODO : poll for order status
                    event = {}
                await self.__event_sink.on_event(channel, event)

            await self.pantheon.sleep(poll_interval_s)

    async def __finalised_order_cleanup(self, poll_interval_s):
        _logger.debug(
            f'Start polling for removing {self.finalised_orders_cleanup_after_s}s earlier finalised orders every {poll_interval_s}s')

        while True:
            for order in self.__orders.values():
                if order.finalised and order.finalised_at + self.finalised_orders_cleanup_after_s < int(time.time()):
                    self.__orders.pop(order.client_oId)
                    self.__client_oid_to_nonce.pop(order.client_oId)

            await self.pantheon.sleep(poll_interval_s)

    async def start(self, private_key, secrets):
        self.__instruments = await self.pantheon.get_instruments_live_source(
            exchanges=['uni3'],
            symbols=[],
            kinds=[],
            usage=InstrumentUsageExchanges.TradableOnly,
            lifecycles=[InstrumentLifecycle.ACTIVE],
            rmq_conn_name='read')

        await self.__api.initialize(private_key)

        poll_interval_s = self.__config['poll_interval_s']
        self.pantheon.spawn(self.__poll_order_for_status(poll_interval_s))
        self.pantheon.spawn(self.__finalised_order_cleanup(poll_interval_s))
