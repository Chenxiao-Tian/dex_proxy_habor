import asyncio
import logging
import json
import os
from typing import Dict, List
from decimal import Decimal

from pantheon import Pantheon
from pantheon.market_data_types import Side

from pyutils.exchange_apis.dexalot_api import *
from pyutils.exchange_connectors import ConnectorType
from pyutils.gas_pricing.eth import GasPriceTracker, PriorityFee

from ..dex_common import DexCommon


class Dexalot(DexCommon):
    CHANNELS = ['ORDER', 'TRADE']

    def __init__(self, pantheon: Pantheon, config, server, event_sink):
        super().__init__(pantheon, ConnectorType.Dexalot, config, server, event_sink)

        self.__order_queue = asyncio.Queue()
        self.__trade_queue = asyncio.Queue()

        self.__estimate_gas_limit = config.get('estimate_gas_limit', False)
        self.__default_insert_gas_limit = config.get('default_insert_gas_limit', 1000000)
        self.__default_cancel_gas_limit = config.get('default_cancel_gas_limit', 500000)

        self.__gas_price_trackers = {}
        for name, value in config['gas_price_trackers'].items():
            self.__gas_price_trackers[name] = GasPriceTracker(pantheon, value)

        self._server.register('POST', '/private/remove-gas-from-tank', self.transfer)
        self._server.register('POST', '/private/fill-up-gas-tank', self.transfer)
        self._server.register('POST', '/private/deposit-into-subnet', self.transfer)
        self._server.register('POST', '/private/withdraw-from-subnet', self.transfer)

        self._server.register('GET', '/public/get-order', self.__get_order)
        self._server.register('POST', '/private/insert-order', self.__insert_order)
        self._server.register('DELETE', '/private/cancel-order', self.__cancel_order)

        self._server.register('POST', '/private/fill-up-nonce-gap', self.__fill_up_nonce_gap)

        self._server.register('GET', '/public/get-proof', self.__get_proof)

    async def on_new_connection(self, ws):
        ready = self._api.get_public_websocket_status().is_ready()
        await self.__notify_node_connected(ready, ws)

    async def __get_proof(self, path, params: dict, received_at_ms):
        try:
            address, signature = self._api.subnet.get_proof()
            return 200, {'result': {'address': address, 'signature': signature}}
        except Exception as e:
            self._logger.exception(f'Failed to get proof: %r', e)
            return 400, {'error': {'message': str(e)}}

    async def process_request(self, ws, request_id, method, params: dict):
        return False

    async def on_request_status_update(self, client_request_id, request_status, tx_receipt: dict):
        await super().on_request_status_update(client_request_id, request_status)

    async def _amend_transaction(self, request, params, gas_price_wei):
        if request.request_type == RequestType.TRANSFER:
            return await self._transfer(request.request_path, request.symbol, request.address_to, request.amount,
                                        request.gas_limit, gas_price_wei, request.nonce)
        elif request.request_type == RequestType.APPROVE:
            return await self._approve(request.symbol, request.amount, request.gas_limit, gas_price_wei,
                                       nonce=request.nonce)
        else:
            raise RuntimeError(f'Unable to amend request type {request.request_type.name}')

    async def _cancel_transaction(self, request, gas_price_wei):
        if request.request_type == RequestType.APPROVE:
            return await self._api.mainnet.cancel_transaction(request.nonce, gas_price_wei)
        elif request.request_type == RequestType.TRANSFER:
            if request.request_path in ['/private/withdraw', '/private/deposit-into-subnet']:
                return self._api.mainnet.cancel_transaction(request.nonce, gas_price_wei)
            else:
                return self._api.subnet.cancel_transaction(request.nonce, gas_price_wei)
        elif request.request_type == RequestType.ORDER:
            raise NotImplementedError()
        else:
            assert False

    async def _approve(self, symbol, amount, gas_limit, gas_price_wei, nonce=None):
        self._logger.debug(f'Approving deposit into subnet: symbol={symbol}, amount={amount}')
        return await self._api.mainnet.approve_deposit_into_subnet(symbol, amount, gas_limit, gas_price_wei, nonce)

    async def _transfer(self, path, symbol, address_to, amount, gas_limit, gas_price_wei, nonce=None):
        if path == '/private/withdraw':
            self._logger.debug(
                f'Withdrawing from mainnet: symbol={symbol}, amount={amount}, address_to={address_to}')
            return await self._api.mainnet.withdraw(symbol, address_to, amount, gas_limit, gas_price_wei, nonce)
        elif path == '/private/withdraw-from-subnet':
            self._logger.debug(f'Withdrawing from subnet: symbol={symbol}, amount={amount}')
            return await self._api.subnet.withdraw_to_mainnet(symbol, amount, gas_limit, gas_price_wei, nonce)
        elif path == '/private/remove-gas-from-tank':
            self._logger.debug(f'Removing gas from tank: amount={amount}')
            return await self._api.subnet.remove_gas_from_tank(amount, gas_limit, gas_price_wei, nonce)
        elif path == '/private/deposit-into-subnet':
            self._logger.debug(f'Depositing into subnet: symbol={symbol}, amount={amount}')
            return await self._api.mainnet.deposit_into_subnet(symbol, amount, gas_limit, gas_price_wei, nonce)
        elif path == '/private/fill-up-gas-tank':
            self._logger.debug(f'Filling up gas tank: amount={amount}')
            return await self._api.subnet.fill_up_gas_tank(amount, gas_limit, gas_price_wei, nonce)
        else:
            assert False

    async def get_transaction_receipt(self, request, tx_hash):
        if self.__is_mainnet_request(request):
            return await self._api.mainnet.get_transaction_receipt(tx_hash)
        elif self.__is_subnet_request(request):
            return await self._api.subnet.get_transaction_receipt(tx_hash)
        else:
            raise RuntimeError(f'Neither a mainnet request or a subnet request, client_request_id='
                               f'{request.client_request_id}')

    def _get_gas_price(self, request, priority_fee: PriorityFee):
        if self.__is_mainnet_request(request):
            return self.__gas_price_trackers[self._api.mainnet.name].get_gas_price(priority_fee=priority_fee)
        elif self.__is_subnet_request(request):
            return self.__gas_price_trackers[self._api.subnet.name].get_gas_price(priority_fee=priority_fee)
        else:
            raise RuntimeError(f'Neither a mainnet request or a subnet request, client_request_id='
                               f'{request.client_request_id}')

    async def __fill_up_nonce_gap(self, path, params: dict, received_at_ms):
        try:
            env = params['env']
            nonce = params['nonce']
            gas_price_wei = params.get('gas_price_wei')
            if gas_price_wei is None:
                gas_price_wei = self.__gas_price_trackers[env].get_gas_price(priority_fee=PriorityFee.Fast)

            self._logger.debug(f'Filling up nonce gap: nonce={nonce}, gas_price_wei={gas_price_wei}')

            if env == self._api.mainnet.name:
                result = await self._api.mainnet.fill_up_nonce_gap(nonce, int(gas_price_wei))
            elif env == self._api.subnet.name:
                result = await self._api.subnet.fill_up_nonce_gap(nonce, int(gas_price_wei))
            else:
                return 400, {'error': {'message': f'Unknown env {env}'}}

            if result.error_type == ErrorType.NO_ERROR:
                return 200, {'result': {'tx_hash': result.tx_hash}}
            else:
                return 400, {'error': {'code': result.error_type.value, 'message': result.error_message}}

        except Exception as e:
            self._logger.exception(f'Failed to fill up nonce gap: %r', e)
            return 400, {'error': {'message': repr(e)}}

    async def __insert_order(self, path, params: dict, received_at_ms):
        try:
            client_order_id = params['client_order_id']
            symbol = params['symbol']
            price = Decimal(params['price'])
            qty = Decimal(params['qty'])
            assert params['side'] == 'BUY' or params['side'] == 'SELL', 'Unknown order side'
            side = Side.BUY if params['side'] == 'BUY' else Side.SELL
            type1 = OrderType1(params['type1'])
            type2 = OrderType2(params['type2'])
            gas_price_wei = params['gas_price_wei']
            if gas_price_wei is None:
                gas_price_wei = self.__gas_price_trackers[self._api.subnet.name].get_gas_price(priority_fee=PriorityFee.Med)
            timeout = int(params.get('timeout', 0))

            gas_limit = None if self.__estimate_gas_limit else self.__default_insert_gas_limit

            self._logger.debug(
                f'Inserting order: client_order_id={client_order_id}, symbol={symbol}, price={price}, qty={qty}, side={side.name},'
                f' type1={type1.name}, type2={type2.name}, gas_limit={gas_limit}, gas_price_wei={gas_price_wei}, '
                f'timeout={timeout}s')

            result = await self._api.subnet.insert_order(client_order_id, symbol, price, qty, side, type1, type2, gas_limit,
                                                         int(gas_price_wei), timeout=timeout)
            if result.error_type == ErrorType.NO_ERROR:
                return 200, {'result': {'orders': [order.to_dict() for order in result.orders],
                                        'trades': [trade.to_dict() for trade in result.trades]}}
            else:
                return 400, {'error': {'code': result.error_type.value, 'message': result.error_message}}

        except Exception as e:
            self._logger.exception(f'Failed to insert order: %r', e)
            return 400, {'error': {'message': repr(e)}}

    async def __cancel_order(self, path, params: dict, received_at_ms):
        try:
            order_id = params['order_id']
            gas_price_wei = params.get('gas_price_wei')
            if gas_price_wei is None:
                gas_price_wei = self.__gas_price_trackers[self._api.subnet.name].get_gas_price(priority_fee=PriorityFee.Fast)

            # timeout is part of the query string, converts it to integer
            timeout = int(params.get('timeout', 0))

            gas_limit = None if self.__estimate_gas_limit else self.__default_cancel_gas_limit

            self._logger.debug(f'Canceling order: order_id={order_id}, gas_limit={gas_limit}, gas_price_wei={gas_price_wei}, '
                               f'timeout={timeout}s')
            result = await self._api.subnet.cancel_order(order_id, gas_limit, int(gas_price_wei), timeout=timeout)
            if result.error_type == ErrorType.NO_ERROR:
                return 200, {'result': {'orders': [order.to_dict() for order in result.orders],
                                        'trades': [trade.to_dict() for trade in result.trades]}}
            else:
                self._logger.error(f'Can not cancel order {order_id}: {result.error_message}')
                return 400, {'error': {'code': result.error_type.value, 'message': result.error_message}}

        except Exception as e:
            self._logger.exception(f'Failed to cancel orders: %r', e)
            return 400, {'error': {'message': repr(e)}}

    async def _cancel_all(self, path, params, received_at_ms):
        try:
            request_type = RequestType[params['request_type']]
            if request_type == RequestType.ORDER:
                return await self.__cancel_all_orders(params)
            else:
                return await super()._cancel_all(path, params, received_at_ms)

        except Exception as e:
            self._logger.exception(f'Failed to cancel all: %r', e)
            return 400, {'error': {'message': str(e)}}

    async def __cancel_all_orders(self, params):
        """
        Cancel all open orders.

        Returns 200 if all open orders are cancelled, otherwise returns 400 if any cancel fails.
        Additionally, both will return a list of canceled orders and failed orders respectively.
        """
        try:
            self._logger.debug('Canceling all open orders')
            address, signature = self._api.subnet.get_proof()
            orders = await self._api.get_open_orders(f'{address}:{signature}')
            if not orders:
                self._logger.debug('No open orders to cancel')
                return 200, {'result': {'canceled_orders': [], 'failed_order_ids': []}}

            order_ids = []
            client_order_ids = {}
            for order in orders:
                order_ids.append(order.order_id)
                client_order_ids[order.order_id] = order.client_order_id

            gas_price_wei = self.__gas_price_trackers[self._api.subnet.name].get_gas_price(priority_fee=PriorityFee.Fast)

            timeout = int(params.get('timeout', 0))

            self._logger.debug(f'Canceling {len(order_ids)} open orders: {order_ids}')

            # Not advised to send an array more than 15-20 ids to avoid running out of gas
            batch_size = 10
            gas_limit = None if self.__estimate_gas_limit else self.__default_cancel_gas_limit * batch_size

            batches = [order_ids[i:i + batch_size] for i in range(0, len(order_ids), batch_size)]
            failed_order_ids = []
            canceled_orders = []
            for batch in batches:
                self._logger.debug(f'Bulk canceling orders {batch}, gas_limit={gas_limit}, gas_price_wei={gas_price_wei}, '
                                   f'timeout={timeout}s')
                result = await self._api.subnet.bulk_cancel(batch, gas_limit, gas_price_wei, timeout=timeout)
                if result.error_type != ErrorType.NO_ERROR:
                    self._logger.error(f'Can not cancel orders {batch}: {result.error_message}')
                    failed_order_ids.extend(batch)
                else:
                    self._logger.debug(f'Canceled orders {batch}')
                    for order in result.orders:
                        if order.client_order_id == '':
                            order.client_order_id = client_order_ids.get(order.order_id, '')
                        canceled_orders.append(order.to_dict())

            return 200, {'result': {'canceled_orders': canceled_orders, 'failed_order_ids': failed_order_ids}}

        except Exception as e:
            self._logger.exception(f'Failed to cancel all orders: %r', e)
            return 400, {'error': {'message': repr(e)}}

    async def _get_all_open_requests(self, path, params, received_at_ms):
        try:
            request_type = RequestType[params['request_type']]
            if request_type == RequestType.ORDER:
                address, signature = self._api.subnet.get_proof()
                orders = await self._api.get_open_orders(f'{address}:{signature}')
                return 200, {'result': [order.to_dict() for order in orders]}
            else:
                return await super()._get_all_open_requests(path, params, received_at_ms)

        except Exception as e:
            self._logger.exception(f'Failed to get all open requests: %r', e)
            return 400, {'error': {'message': str(e)}}

    async def __get_order(self, path, params, received_at_ms):
        try:
            order_id = params.get('order_id')
            client_order_id = params.get('client_order_id')
            if order_id is None and client_order_id is None:
                return 400, {'error': {'message': 'Either order id or client order id must be provided'}}

            self._logger.debug(f'Getting order: order_id={order_id}, client_order_id={client_order_id}')
            order = await self._api.subnet.get_order(order_id, client_order_id)
            if order is None:
                return 404, {'error': {'message': 'Order not found'}}
            self._logger.debug(f'Got {order}')
            return 200, {'result': order.to_dict()}

        except Exception as e:
            self._logger.exception(f'Failed to get order: %r', e)
            return 400, {'error': {'message': str(e)}}

    @staticmethod
    def __is_mainnet_request(request):
        if request.request_type == RequestType.ORDER:
            return False

        if request.request_type == RequestType.APPROVE:
            return True

        return request.request_path in ['/private/withdraw',
                                        '/private/deposit-into-subnet']

    @staticmethod
    def __is_subnet_request(request):
        if request.request_type == RequestType.ORDER:
            return True

        if request.request_type == RequestType.APPROVE:
            return False

        return request.request_path in ['/private/remove-gas-from-tank',
                                        '/private/fill-up-gas-tank',
                                        '/private/withdraw-from-subnet']

    async def start(self, private_key):
        await super().start(private_key)

        for gas_price_tracker in self.__gas_price_trackers.values():
            await gas_price_tracker.start()
            await gas_price_tracker.wait_gas_price_ready()

        await self._api.initialize(private_key)

        mainnet_max_nonce_loaded = self._request_cache.get_max_nonce(self.__is_mainnet_request)
        self._logger.debug(f'Mainnet max nonce loaded: {mainnet_max_nonce_loaded}')
        self._api.mainnet.initialize_nonce(mainnet_max_nonce_loaded)

        subnet_max_nonce_loaded = self._request_cache.get_max_nonce(self.__is_subnet_request)
        self._logger.debug(f'Subnet max nonce loaded: {subnet_max_nonce_loaded}')
        self._api.subnet.initialize_nonce(subnet_max_nonce_loaded)

        file_prefix = os.path.dirname(os.path.realpath(__file__))
        addresses_whitelists_file_path = f'{file_prefix}/../../resources/dexa_address_whitelists.json'
        self._logger.debug(f'Loading addresses whitelists from {addresses_whitelists_file_path}')
        with open(addresses_whitelists_file_path, 'r') as f:
            whitelists = json.load(f)

            mainnet_whitelists = whitelists[self._api.mainnet.name]
            # whitelisting exchange contracts and token contracts in mainnet
            for exchange_contract in mainnet_whitelists["exchange_contracts"]:
                deployment_type = DeploymentType(exchange_contract["deployment_type"])
                address = exchange_contract["address"]
                self._api.mainnet.whitelist_exchange_contract(deployment_type, address)

            for token in mainnet_whitelists['tokens']:
                symbol = token["symbol"]
                if symbol in self._withdrawal_address_whitelists:
                    raise RuntimeError(f'Duplicate token {symbol} in contracts address file')

                if "valid_withdrawal_addresses" in token:
                    self._withdrawal_address_whitelists[symbol] = token["valid_withdrawal_addresses"]

                if "address" in token:
                    address = token["address"]
                    self._api.mainnet.whitelist_token(symbol, address)

            # whitelisting exchange contracts in subnet
            subnet_whitelists = whitelists[self._api.subnet.name]
            for exchange_contract in subnet_whitelists["exchange_contracts"]:
                deployment_type = DeploymentType(exchange_contract["deployment_type"])
                address = exchange_contract["address"]
                self._api.subnet.whitelist_exchange_contract(deployment_type, address)

        self.pantheon.spawn(self.__connect_to_exchange())

    async def __connect_to_exchange(self):
        self._logger.debug('Connecting to exchange')

        self.pantheon.spawn(self.__receive_orders())
        self.pantheon.spawn(self.__receive_trades())

        await self.__subscribe(EventType.ORDER_STATUS_CHANGED)
        await self.__subscribe(EventType.EXECUTED)

        await self._api.get_public_websocket_status().wait_until_connected()
        await self.__notify_node_connected(True)

        while True:
            await self._api.get_public_websocket_status().wait_until_disconnected()
            await self.__notify_node_connected(False)

            await self._api.get_public_websocket_status().wait_until_connected()

            await self.__subscribe(EventType.ORDER_STATUS_CHANGED)
            await self.__subscribe(EventType.EXECUTED)

            await self.__notify_node_connected(True)

    async def __notify_node_connected(self, connected: bool, ws=None):
        notification = {
            'jsonrpc': '2.0',
            'method': 'notification',
            'params': {
                'node_connected': connected
            }
        }
        await self._server.send_json(ws, notification)

    async def __subscribe(self, event_type: EventType):
        while True:
            try:
                if event_type == EventType.ORDER_STATUS_CHANGED:
                    self._logger.info("Subscribing to order status events")
                    reply = await self._api.subscribe_order_status_event(self._api.subnet.account.address,
                                                                         self.__order_queue)
                elif event_type == EventType.EXECUTED:
                    self._logger.info("Subscribing to trade events")
                    reply = await self._api.subscribe_trade_event(self._api.subnet.account.address,
                                                                  self.__trade_queue)
                else:
                    self._logger.error(f'Unknown event type {event_type}')

                self._logger.info(f"Subscription reply: {reply}")

            except Exception as e:
                self._logger.error("Subscription failed: %r, retrying after 10s", e)
                await self.pantheon.sleep(10)
            else:
                break

    async def __receive_orders(self):
        while True:
            order = await self.__order_queue.get()
            self._logger.debug(f'Received {order}')
            event = {
                'jsonrpc': '2.0',
                'method': 'subscription',
                'params': {
                    'channel': 'ORDER',
                    'data': order.to_dict()
                }
            }
            await self._event_sink.on_event('ORDER', event)

    async def __receive_trades(self):
        while True:
            trade = await self.__trade_queue.get()
            self._logger.debug(f'Received {trade}')

            event = {
                'jsonrpc': '2.0',
                'method': 'subscription',
                'params': {
                    'channel': 'TRADE',
                    'data': trade.to_dict()
                }
            }
            await self._event_sink.on_event('TRADE', event)
