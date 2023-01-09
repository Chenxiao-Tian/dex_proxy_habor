import logging
from typing import Dict, List
from decimal import Decimal

from pantheon import Pantheon
from pantheon.market_data_types import Side

from pyutils.exchange_apis.dexalot_api import *
from pyutils.exchange_apis import ApiFactory
from pyutils.exchange_connectors import ConnectorFactory, ConnectorType

_logger = logging.getLogger('Dexalot')


class Dexalot:
    CHANNELS = ['ORDER', 'TRADE']

    def __init__(self, pantheon: Pantheon, config, server, event_sink):
        self.pantheon = pantheon
        self.__config = config
        self.__server = server
        self.__event_sink = event_sink

        api_factory = ApiFactory(ConnectorFactory(config.get('connectors')))
        self.__api = api_factory.create(self.pantheon, ConnectorType.Dexalot)

        self.__server.register('GET', '/public/get-order', self.__get_order)
        self.__server.register('GET', '/public/get-open-orders', self.__get_open_orders)
        self.__server.register('GET', '/public/get-exchange-balance', self.__get_exchange_balance)
        self.__server.register('POST', '/private/remove-gas-from-tank', self.__remove_gas_from_tank)
        self.__server.register('POST', '/private/fill-up-gas-tank', self.__fill_up_gas_tank)
        self.__server.register('POST', '/private/deposit', self.__deposit)
        self.__server.register('POST', '/private/withdraw', self.__withdraw)
        self.__server.register('POST', '/private/insert-order', self.__insert_order)
        self.__server.register('DELETE', '/private/cancel-order', self.__cancel_order)
        self.__server.register('DELETE', '/private/cancel-all', self.__cancel_all)

    async def process_request(self, ws, request_id, method, params: dict):
        return False

    async def __insert_order(self, params: dict):
        try:
            client_oid = params['client_order_id']
            symbol = params['symbol']
            price = Decimal(params['price'])
            qty = Decimal(params['qty'])
            assert params['side'] == 'BUY' or params['side'] == 'SELL', 'Unknown order side'
            side = Side.BUY if params['side'] == 'BUY' else Side.SELL
            type1 = OrderType1(params['type1'])
            type2 = OrderType2(params['type2'])
            timeout = params.get('timeout')
            timeout_s = int(timeout) if timeout else 0

            _logger.debug(f'Inserting order: client_oid={client_oid}, symbol={symbol}, price={price}, qty={qty}, side={side.name}, type1={type1.name}, type2={type2.name}, timeout_s={timeout_s}')
            result = self.__api.subnet.insert_order(client_oid, symbol, price, qty, side, type1, type2, timeout_s)
            if result.error_type == ErrorType.NO_ERROR:
                return 200, {'result': {'client_order_id': client_oid}}
            else:
                return 400, {'error': {'code': result.error_type.value, 'message': self.__api.get_error_description(result)}}
        except Exception as e:
            _logger.exception(f'Failed to insert order: %r', e)
            return 400, {'error': {'message': repr(e)}}

    async def __cancel_order(self, params: dict):
        try:
            order_id = params['order_id']
            timeout = params.get('timeout')
            timeout_s = int(timeout) if timeout else 0

            _logger.debug(f'Canceling order: oid={order_id}, timeout_s={timeout_s}')
            result = self.__api.subnet.cancel_order(order_id, timeout_s)
            if result.error_type == ErrorType.NO_ERROR:
                return 200, {'result': {'order_id': order_id}}
            else:
                return 400, {'error': {'code': result.error_type.value, 'message': self.__api.get_error_description(result)}}
        except Exception as e:
            _logger.exception(f'Failed to cancel orders: %r', e)
            return 400, {'error': {'message': repr(e)}}

    async def __cancel_all(self, params):
        '''
        Cancel all open orders.

        Returns 200 if all open orders are cancelled, otherwise returns 400 if any cancel fails.
        Additionally both will return a list of canceled orders and failed orders respectively.
        '''
        _logger.debug('Canceling all open orders')
        http_code, data = await self.__get_open_orders({})
        if http_code != 200:
            return 400, {'error': {'message': 'Can not cancel all orders: {}, please try again'.format(data['error']['message'])}}

        if not data:
            _logger.debug('No open orders to cancel')
            return 200, {'canceled': [], 'failed': []}

        order_ids = [order['oid'] for order in data]
        _logger.debug(f'Canceling {len(order_ids)} open orders: {order_ids}')
        # Not advised to send an array more than 15-20 ids to avoid running out of gas
        batch_size = 10
        batches = [order_ids[i:i + batch_size] for i in range(0, len(order_ids), batch_size)]
        canceled_orders = []
        failed_orders = []
        for batch in batches:
            # same timeout used as es
            _logger.debug(f'Bulk canceling orders {batch}')
            result = self.__api.subnet.bulk_cancel(batch, 60)
            if result.error_type != ErrorType.NO_ERROR:
                _logger.error(f'Can not cancel orders {batch}: {result.error_message}')
                failed_orders.extend(batch)
            else:
                _logger.error(f'Canceled orders {batch}')
                canceled_orders.extend(batch)
        return 400 if failed_orders else 200, {'canceled': canceled_orders, 'failed': failed_orders}

    async def __get_order(self, params):
        try:
            order_id = params.get('order_id')
            client_oid = params.get('client_order_id')
            if order_id is None and client_oid is None:
                return 400, {'error': {'message': 'Either order id or client order id must be provided'}}

            _logger.debug(f'Getting order: oid={order_id}, client_oid={client_oid}')
            order = self.__api.subnet.get_order(order_id, client_oid)
            if order is None:
                return 404, {'error': {'message': 'Order not found'}}
            _logger.debug(f'Got {order}')
            return 200, order.toDict()
        except Exception as e:
            _logger.exception(f'Failed to get order: %r', e)
            return 400, {'error': {'message': str(e)}}

    async def __get_open_orders(self, params):
        try:
            symbol = params.get('symbol')
            orders = await self.__api.get_open_orders(self.__api.subnet.account.address, symbol)
            return 200, [order.toDict() for order in orders]
        except Exception as e:
            _logger.exception(f'Failed to get open orders: %r', e)
            return 400, {'error': {'message': str(e)}}

    async def __remove_gas_from_tank(self, params):
        try:
            amount = Decimal(params['amount'])
            timeout = params.get('timeout')
            timeout_s = int(timeout) if timeout else 0

            _logger.debug(f'Removing gas from tank: amount={amount}, timeout_s={timeout_s}')
            result = self.__api.subnet.remove_gas_from_tank(amount, timeout_s)
            if result.error_type != ErrorType.NO_ERROR:
                return 400, {'error': {'code': result.error_type.value, 'message': self.__api.get_error_description(result)}}
            else:
                return 200, {'tx_hash': result.tx_hash}
        except Exception as e:
            _logger.exception(f'Failed to fill up gas tank: %r', e)
            return 400, {'error': {'message': str(e)}}

    async def __fill_up_gas_tank(self, params):
        try:
            amount = Decimal(params['amount'])
            timeout = params.get('timeout')
            timeout_s = int(timeout) if timeout else 0

            _logger.debug(f'Filling up gas tank: amount={amount}, timeout_s={timeout_s}')
            result = self.__api.subnet.fill_up_gas_tank(amount, timeout_s)
            if result.error_type != ErrorType.NO_ERROR:
                return 400, {'error': {'code': result.error_type.value, 'message': self.__api.get_error_description(result)}}
            else:
                return 200, {'tx_hash': result.tx_hash}
        except Exception as e:
            _logger.exception(f'Failed to fill up gas tank: %r', e)
            return 400, {'error': {'message': str(e)}}

    async def __get_exchange_balance(self, params):
        try:
            symbol = params['symbol']
            _logger.debug(f'Getting exchange balance: symbol={symbol}')
            balance = self.__api.subnet.get_exchange_balance(symbol)
            return 200, {'result': {symbol: balance}}
        except Exception as e:
            _logger.exception(f'Failed to get exchange balance: %r', e)
            return 400, {'error': {'message': str(e)}}

    async def __deposit(self, params):
        try:
            symbol = params['symbol']
            amount = Decimal(params['amount'])
            timeout = params.get('timeout')
            timeout_s = int(timeout) if timeout else 0

            _logger.debug(f'Depositing: symbol={symbol}, amount={amount}, timeout_s={timeout_s}')
            result = self.__api.mainnet.deposit(symbol, amount, timeout_s)
            if result.error_type != ErrorType.NO_ERROR:
                return 400, {'error': {'code': result.error_type.value, 'message': self.__api.get_error_description(result)}}
            else:
                return 200, {'tx_hash': result.tx_hash}
        except Exception as e:
            _logger.exception(f'Failed to deposit: %r', e)
            return 400, {'error': {'message': str(e)}}

    async def __withdraw(self, params):
        try:
            symbol = params['symbol']
            amount = Decimal(params['amount'])
            timeout = params.get('timeout')
            timeout_s = int(timeout) if timeout else 0

            _logger.debug(f'Withdrawing: symbol={symbol}, amount={amount}, timeout_s={timeout_s}')
            result = self.__api.subnet.withdraw(symbol, amount, timeout_s)
            if result.error_type != ErrorType.NO_ERROR:
                return 400, {'error': {'code': result.error_type.value, 'message': self.__api.get_error_description(result)}}
            else:
                return 200, {'tx_hash': result.tx_hash}
        except Exception as e:
            _logger.exception(f'Failed to withdraw: %r', e)
            return 400, {'error': {'message': str(e)}}

    async def __poll_order_event(self, poll_interval):
        _logger.debug(f'Start polling order event every {poll_interval}s')
        channel = 'ORDER'
        while True:
            async for order in self.__api.subnet.get_order_events():
                event = {
                    'jsonrpc': '2.0',
                    'method': 'subscription',
                    'params': {
                        'channel': channel,
                        'data': order.toDict()
                    }
                }

                await self.__event_sink.on_event(channel, event)

            await self.pantheon.sleep(poll_interval)

    async def __poll_trade_event(self, poll_interval):
        _logger.debug(f'Start polling trade event every {poll_interval}s')
        channel = 'TRADE'
        while True:
            async for trade in self.__api.subnet.get_trade_events():
                _logger.debug(f'Received {trade}')
                event = {
                    'jsonrpc': '2.0',
                    'method': 'subscription',
                    'params': {
                        'channel': channel,
                        'data': trade.toDict()
                    }
                }

                await self.__event_sink.on_event(channel, event)

            await self.pantheon.sleep(poll_interval)

    async def start(self, private_key, secrets):
        await self.__api.initialize(private_key)

        poll_interval_s = self.__config['poll_interval_s']
        self.pantheon.spawn(self.__poll_order_event(poll_interval_s))
        self.pantheon.spawn(self.__poll_trade_event(poll_interval_s))
