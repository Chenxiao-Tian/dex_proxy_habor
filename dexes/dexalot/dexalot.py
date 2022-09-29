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
        self.__server.register('POST', '/private/remove-gas-from-tank/', self.__remove_gas_from_tank)
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

            _logger.debug(f'Inserting order: client_oid={client_oid}, symbol={symbol}, price={price}, qty={qty}, side={side.name}, type1={type1.name}, type2={type2.name}, timeout_s={timeout}')
            result = self.__api.insert_order(client_oid, symbol, price, qty, side, type1, type2, timeout)
            if result.error == TransactionError.NO_ERROR:
                return 200, {'result': {'client_order_id': client_oid}}
            else:
                return 400, {'error': {'code': result.error.value, 'message': result.message}}
        except Exception as e:
            _logger.exception(f'Failed to insert order: %r', e)
            return 400, {'error': {'message': repr(e)}}

    async def __cancel_order(self, params: dict):
        try:
            order_id = params['order_id']
            timeout = int(params.get('timeout'))
            _logger.debug(f'Canceling order: order-id={order_id}, timeout={timeout}')
            result = self.__api.cancel_order(order_id, timeout)
            if result.error == TransactionError.NO_ERROR:
                return 200, {'result': {'order_id': order_id}}
            else:
                return 400, {'error': {'code': result.error.value, 'message': result.message}}
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
            result = self.__api.bulk_cancel(batch, 60)
            if result.error != TransactionError.NO_ERROR:
                _logger.error(f'Can not cancel orders {batch}: {result.message}')
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
        pass

    async def __fill_up_gas_tank(self, params):
        pass

    async def __deposit(self, params):
        pass

    async def __withdraw(self, params):
        pass

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
