from abc import ABC, abstractmethod
import logging

from pantheon import Pantheon

from .requests_cache import RequestsCache
from .transactions_status_poller import TransactionsStatusPoller

from pyutils.gas_pricing.eth import PriorityFee
from pyutils.exchange_connectors import ConnectorFactory, ConnectorType
from pyutils.exchange_apis import ApiFactory
from pyutils.exchange_apis.dex_common import *


class DexCommon(ABC):
    """
    The DexCommon class is a base class for all common request handlers to inherit from.

    All the abstract methods must be implemented in any subclass in order to work with DexCommon.
    Any dex specific logic should be handled in a subclass.
    """

    def __init__(self, pantheon: Pantheon, connector_type: ConnectorType, config, server: 'WebServer', event_sink: 'DexProxy'):
        self.pantheon = pantheon

        api_factory = ApiFactory(ConnectorFactory(config.get('connectors')))
        self._api = api_factory.create(self.pantheon, connector_type)

        self._logger = logging.getLogger(config['name'])

        self._server = server
        self._event_sink = event_sink

        self._request_cache = RequestsCache(pantheon, config['request_cache'])
        self._transactions_status_poller = TransactionsStatusPoller(pantheon, config['transactions_status_poller'], self)

        if 'max_allowed_gas_price_gwei' in config:
            self.__max_allowed_gas_price_wei = config['max_allowed_gas_price_gwei'] * 10 ** 9
        else:
            self.__max_allowed_gas_price_wei = None

        # symbol -> list of whitelisted withdrawal addresses
        self._withdrawal_address_whitelists = {}

        self._server.register('POST', '/private/approve-token', self.__approve_token)
        self._server.register('POST', '/private/withdraw', self.transfer)
        self._server.register('POST', '/private/amend-request', self.__amend_request)
        self._server.register('DELETE', '/private/cancel-request', self.__cancel_request)
        self._server.register('DELETE', '/private/cancel-all', self._cancel_all)
        self._server.register('GET', '/public/get-all-open-requests', self._get_all_open_requests)
        self._server.register('GET', '/public/get-request-status', self.__get_request_status)

    @abstractmethod
    async def on_new_connection(self, ws):
        """
        Notified of a new connection which might be used to push status by subclass
        """
        pass

    @abstractmethod
    async def process_request(self, ws, request_id, method, params: dict):
        """
        Processes any dex specific websocket messages in subclass.
        Return True if it's processed, otherwise False so the unprocessed message will be alerted.
        """
        pass

    @abstractmethod
    async def _approve(self, symbol, amount, gas_limit, gas_price_wei, nonce=None):
        """
        Initiates a transaction to allow a designated spender to use a certain amount of token.
        """
        pass

    @abstractmethod
    async def _transfer(self, path, symbol, address_to, amount, gas_limit, gas_price_wei, nonce=None):
        """
        Initiates a transaction to transfer a certain amount of token to a designated address.
        """
        pass

    @abstractmethod
    async def _amend_transaction(self, request, params, gas_price_wei):
        """
        Initiates a new transaction identical to the old transaction but with greater gas price.
        """
        pass

    @abstractmethod
    async def _cancel_transaction(self, request, gas_price_wei):
        """
        Initiates a new transaction with same nonce of the old transaction and greater gas price.
        """
        pass

    @abstractmethod
    async def get_transaction_receipt(self, request, tx_hash):
        pass

    @abstractmethod
    def _get_gas_price(self, request, priority_fee: PriorityFee):
        pass

    @abstractmethod
    async def on_request_status_update(self, client_request_id, request_status):
        """
        Called when a request status is changed, usually by `TransactionsStatusPoller`
        The default implementation is merely to finalise the request.
        """
        self._request_cache.finalise_request(client_request_id, request_status)

    @abstractmethod
    async def start(self, private_key):
        await self._transactions_status_poller.start()
        await self._request_cache.start(self._transactions_status_poller)

    def get_request(self, client_request_id):
        self._logger.debug(f'Getting request: client_request_id={client_request_id}')
        return self._request_cache.get(client_request_id)

    async def __get_request_status(self, path, params, received_at_ms):
        try:
            client_request_id = params['client_request_id']
            request = self.get_request(client_request_id)
            if request:
                return 200, request.to_dict()
            else:
                return 404, {'error': {'message': 'Request not found'}}

        except Exception as e:
            self._logger.exception(f'Failed to get request: %r', e)
            return 400, {'error': {'message': str(e)}}

    @abstractmethod
    async def _get_all_open_requests(self, path, params, received_at_ms):
        try:
            assert params['request_type'] == 'ORDER' or params['request_type'] == 'TRANSFER' or \
                   params['request_type'] == 'APPROVE', 'Unknown request type'
            request_type = RequestType[params['request_type']]

            self._logger.debug(f'Getting all open requests: request_type={request_type.name}')
            return 200, [request.to_dict() for request in self._request_cache.get_all(request_type)]

        except Exception as e:
            self._logger.exception(f'Failed to get all open requests: %r', e)
            return 400, {'error': {'message': str(e)}}

    async def __cancel_request(self, path, params: dict, received_at_ms):
        try:
            client_request_id = params['client_request_id']
            request = self.get_request(client_request_id)
            if request is None:
                return 404, {'error': {'message': 'request not found'}}

            if request.is_finalised():
                return 400, {'error': {'message': f'Cannot cancel. Request status={request.request_status.name}'}}

            if 'gas_price_wei' in params:
                gas_price_not_set_on_request = False
                gas_price_wei = int(params['gas_price_wei'])
            else:
                gas_price_not_set_on_request = True
                gas_price_wei = self._get_gas_price(request, priority_fee=PriorityFee.Fast)

            if gas_price_not_set_on_request:
                if request.request_status == RequestStatus.CANCEL_REQUESTED and \
                        request.used_gas_prices_wei[-1] >= gas_price_wei:
                    return 400, {'error': {'message': f'Cancel with greater than or equal to the '
                                                      f'gas_price_wei={gas_price_wei} already in progress'}}

                # replacement transaction should have gas_price at least greater than 10% of the last gas_price used otherwise
                # 'replacement transaction underpriced' error will occur. https://ethereum.stackexchange.com/a/44875
                gas_price_wei = max(gas_price_wei, int(1.1 * request.used_gas_prices_wei[-1]))

            ok, reason = self._check_max_allowed_gas_price(gas_price_wei)
            if not ok:
                return 400, {'error': {'message': reason}}

            self._logger.debug(f'Canceling={request}, gas_price_wei={gas_price_wei}')

            result = await self._cancel_transaction(request, gas_price_wei)
            if result.error_type == ErrorType.NO_ERROR:
                request.request_status = RequestStatus.CANCEL_REQUESTED
                request.tx_hashes.append((result.tx_hash, RequestType.CANCEL.name))
                request.used_gas_prices_wei.append(gas_price_wei)

                self._transactions_status_poller.add_for_polling(result.tx_hash, client_request_id, RequestType.CANCEL)
                self._request_cache.add_or_update_request_in_redis(client_request_id)

                if request.request_type == RequestType.ORDER:
                    return 200, {'result': {'order_id': request.order_id}}
                else:
                    return 200, {'result': {'tx_hash': result.tx_hash}}
            else:
                return 400, {'error': {'code': result.error_type.value, 'message': result.error_message}}

        except Exception as e:
            self._logger.exception(f'Failed to cancel request: %r', e)
            return 400, {'error': {'message': repr(e)}}

    @abstractmethod
    async def _cancel_all(self, path, params, received_at_ms):
        try:
            assert params['request_type'] == 'ORDER' or params['request_type'] == 'TRANSFER' \
                   or params['request_type'] == 'APPROVE', 'Unknown transaction type'
            request_type = RequestType[params['request_type']]

            self._logger.debug(f'Canceling all requests, request_type={request_type.name}')

            cancel_requested = []
            failed_cancels = []

            for request in self._request_cache.get_all(request_type):
                gas_price_wei = self._get_gas_price(request, priority_fee=PriorityFee.Fast)

                if request.request_status == RequestStatus.CANCEL_REQUESTED and \
                        request.used_gas_prices_wei[-1] >= gas_price_wei:
                    self.logger.info(
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

            return 400 if failed_cancels else 200, {'cancel_requested': cancel_requested, 'failed_cancels': failed_cancels}

        except Exception as e:
            self._logger.exception(f'Failed to cancel all: %r', e)
            return 400, {'error': {'message': str(e)}}

    async def __approve_token(self, path, params, received_at_ms):
        client_request_id = ''
        try:
            client_request_id = params['client_request_id']

            if self._request_cache.get(client_request_id) is not None:
                return 400, {'error': {'message': f'client_request_id={client_request_id} is already known'}}

            symbol = params['symbol']
            amount = Decimal(params['amount'])
            gas_price_wei = int(params['gas_price_wei'])
            gas_limit = 100000  # TODO: Check for the most suitable value

            ok, reason = self._check_max_allowed_gas_price(gas_price_wei)
            if not ok:
                return 400, {'error': {'message': reason}}

            request = ApproveRequest(client_request_id, symbol, amount, gas_limit, received_at_ms)
            self._logger.debug(f'Approving={request}, gas_price_wei={gas_price_wei}')

            self._request_cache.add(request)

            result = await self._approve(symbol, amount, gas_limit, gas_price_wei)
            if result.error_type == ErrorType.NO_ERROR:
                request.nonce = result.nonce
                request.tx_hashes.append((result.tx_hash, RequestType.APPROVE.name))
                request.used_gas_prices_wei.append(gas_price_wei)

                self._transactions_status_poller.add_for_polling(
                    result.tx_hash, client_request_id, RequestType.APPROVE)
                self._request_cache.add_or_update_request_in_redis(client_request_id)

                return 200, {'tx_hash': result.tx_hash}
            else:
                self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
                return 400, {'error': {'code': result.error_type.value, 'message': result.error_message}}
        except Exception as e:
            self._logger.exception(f'Failed to approve: %r', e)
            self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
            return 400, {'error': {'message': str(e)}}

    async def transfer(self, path, params, received_at_ms):
        client_request_id = ''
        try:
            client_request_id = params['client_request_id']

            if self._request_cache.get(client_request_id) is not None:
                return 400, {'error': {'message': f'client_request_id={client_request_id} is already known'}}

            symbol = params['symbol']
            amount = Decimal(params['amount'])
            gas_limit = int(params['gas_limit'])
            gas_price_wei = int(params['gas_price_wei'])
            # `address_to` is not needed in some cases like transfer from one chain to another in a dual-chain dex
            address_to = params.get('address_to')

            if path == '/private/withdraw':
                ok, reason = self._allow_withdraw(client_request_id, symbol, address_to)
                if not ok:
                    return 400, {'error': {'message': reason}}

            ok, reason = self._check_max_allowed_gas_price(gas_price_wei)
            if not ok:
                return 400, {'error': {'message': reason}}

            transfer = TransferRequest(client_request_id, symbol, amount, address_to, gas_limit, path, received_at_ms)
            self._logger.debug(f'Transferring={transfer}, request_path={path}, gas_price_wei={gas_price_wei}')

            self._request_cache.add(transfer)

            result = await self._transfer(path, symbol, address_to, amount, gas_limit, gas_price_wei)

            transfer.nonce = result.nonce
            if result.error_type == ErrorType.NO_ERROR:
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

    async def __amend_request(self, path, params: dict, received_at_ms):
        try:
            client_request_id = params['client_request_id']
            request = self.get_request(client_request_id)
            if request:
                if request.request_status != RequestStatus.PENDING:
                    return 400, {'error': {'message': f'Cannot amend. Request status={request.request_status.name}'}}

                gas_price_wei = int(params['gas_price_wei'])

                ok, reason = self._check_max_allowed_gas_price(gas_price_wei)
                if not ok:
                    return 400, {'error': {'message': reason}}

                self._logger.debug(f'Amending={request}, gas_price_wei={gas_price_wei}')
                result = await self._amend_transaction(request, params, gas_price_wei)

                if result.error_type == ErrorType.NO_ERROR:
                    request.tx_hashes.append((result.tx_hash, request.request_type.name))
                    request.used_gas_prices_wei.append(gas_price_wei)

                    self._transactions_status_poller.add_for_polling(
                        result.tx_hash, client_request_id, request.request_type)
                    self._request_cache.add_or_update_request_in_redis(client_request_id)

                    if request.request_type == RequestType.ORDER:
                        return 200, {'result': {'order_id': request.order_id}}
                    else:
                        return 200, {'result': {'tx_hash': result.tx_hash}}
                else:
                    return 400, {'error': {'code': result.error_type.value, 'message': result.error_message}}
            else:
                return 404, {'error': {'message': 'request not found'}}

        except Exception as e:
            self._logger.exception(f'Failed to amend request: %r', e)
            return 400, {'error': {'message': repr(e)}}

    def _allow_withdraw(self, client_request_id, symbol, address_to):
        if symbol not in self._withdrawal_address_whitelists:
            self._logger.error(
                f'HIGH ALERT: client_request_id={client_request_id} tried to withdraw unknown symbol={symbol}')
            return False, f'Unknown symbol={symbol}'

        assert address_to is not None
        if address_to not in self._withdrawal_address_whitelists[symbol]:
            self._logger.error(
                f'HIGH ALERT: client_request_id={client_request_id} tried to withdraw symbol={symbol} '
                f'to unknown address={address_to}')
            return False, f'Unknown withdrawal_address={address_to} for symbol={symbol}'

        return True, ''

    def _check_max_allowed_gas_price(self, gas_price_wei):
        if self.__max_allowed_gas_price_wei is not None and gas_price_wei > self.__max_allowed_gas_price_wei:
            return False, f'gas_price_wei={gas_price_wei} is greater than max_allowed_gas_price_wei' \
                          f'={self.__max_allowed_gas_price_wei}'
        return True, ''
