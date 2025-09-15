import logging

from abc import ABC, abstractmethod
from collections import defaultdict
from typing import Optional
from web3 import Web3

from pantheon import Pantheon

from .requests_cache import RequestsCache
from .transactions_status_poller import TransactionsStatusPoller
from .whitelisting_manager_fordefi import WhitelistingManagerFordefi
from .whitelisting_manager_fireblocks import WhitelistingManagerFireblocks

from pyutils.gas_pricing.eth import PriorityFee
from pyutils.exchange_apis.dex_common import *

import py_dex_common.schemas as schemas


class DexCommon(ABC):
    """
    The DexCommon class is a base class for all common request handlers to inherit from.

    All the abstract methods must be implemented in any subclass in order to work with DexCommon.
    Any dex specific logic should be handled in a subclass.
    """

    def __init__(self, pantheon: Pantheon, config, server: "WebServer", event_sink: "DexProxy"):
        self.pantheon = pantheon

        self._logger = logging.getLogger(config['name'])

        self.started = False

        self._config: dict = config
        self._server = server
        self._event_sink = event_sink

        self._request_cache = None
        if "request_cache" in config:
            self._request_cache = RequestsCache(pantheon, config["request_cache"], self)

        self._transactions_status_poller = None
        if "transactions_status_poller" in config:
            self._transactions_status_poller = TransactionsStatusPoller(
                pantheon, config["transactions_status_poller"], self
            )

        if 'max_allowed_gas_price_gwei' in config:
            self.__max_allowed_gas_price_wei = config['max_allowed_gas_price_gwei'] * 10 ** 9
        else:
            self.__max_allowed_gas_price_wei = None

        # from resources file
        # symbol -> list of whitelisted withdrawal addresses
        # created a variable for this so that we don't have to read resources file again and again
        self._withdrawal_address_whitelists_from_res_file = defaultdict(set)
        self._l2_withdrawal_address_whitelist_from_res_file = set()

        # from resources file + API
        # symbol -> list of whitelisted withdrawal addresses
        # whitelisted addresses from API will be refreshed periodically
        self._withdrawal_address_whitelists = defaultdict(set)

        # Temporarily enable full schema for the following dexes
        oapi_support = ["edex", "gte"]  # TODO: use the name from common utils
        self._server.register(
            'POST', '/private/approve-token', self.__approve_token,
            request_model=schemas.ApproveTokenRequest,
            response_model=schemas.TxResponse,
            response_errors={
                400: {"model": schemas.ErrorResponse},
                404: {"model": schemas.ErrorResponse},
                408: {"model": schemas.ErrorResponse},
            },
            summary="Approve ERC20 allowance",
            tags=["private"],
            oapi_in=oapi_support
        )
        self._server.register(
            'POST', '/private/withdraw', self.transfer,
            request_model=schemas.WithdrawRequest,
            response_model=schemas.TxResponse,
            response_errors={
                400: {"model": schemas.ErrorResponse},
                404: {"model": schemas.ErrorResponse},
                408: {"model": schemas.ErrorResponse},
            },
            summary="Submit a withdrawal transfer",
            tags=["private"],
            oapi_in=oapi_support
        )
        self._server.register('POST', '/private/amend-request', self.__amend_request,
                              request_model=schemas.AmendRequestParams,
                              response_model=schemas.AmendRequestSuccess,
                              response_errors={
                                  400: {"model": schemas.ErrorResponse},
                                  404: {"model": schemas.ErrorResponse},
                                  408: {"model": schemas.ErrorResponse},
                              },
                              summary="Amend order",
                              tags=["private"],
                              oapi_in=oapi_support
                              )
        self._server.register('DELETE', '/private/cancel-request', self.__cancel_request,
                              request_model=schemas.CancelRequestParams,
                              response_model=schemas.CancelSuccessResponse,
                              response_errors={
                                  400: {"model": schemas.ErrorResponse},
                                  404: {"model": schemas.ErrorResponse},
                                  408: {"model": schemas.ErrorResponse},
                              },
                              summary="Cancel by request id",
                              tags=["private"],
                              oapi_in=oapi_support
                              )
        self._server.register('DELETE', '/private/cancel-all', self._cancel_all,
                              request_model=schemas.CancelAllParams,
                              response_model=schemas.CancelAllResponse,
                              summary="Cancel all",
                              tags=["private"],
                              oapi_in=oapi_support
                              )
        self._server.register('GET', '/public/get-all-open-requests', self._get_all_open_requests,
                              request_model=schemas.GetAllOpenRequestsParams,
                              response_model=schemas.GetAllOpenRequestsResponse,
                              summary="Get orders, transfers, approvals or wrap/unwraps",
                              tags=["public"],
                              oapi_in=oapi_support
                              )
        self._server.register('GET', '/public/get-request-status', self.__get_request_status,
                              request_model=schemas.GetRequestStatusParams,
                              response_model=schemas.GetRequestStatusResponse,
                              summary="Get the status of requests by client_request_id",
                              tags=["public"],
                              oapi_in=oapi_support
                              )
        self._server.register('GET', '/public/status', self.__get_status,
                              request_model=schemas.StatusParams,
                              response_model=schemas.StatusResponse,
                              summary="Get the system status",
                              tags=["public"],
                              oapi_in=oapi_support
                              )

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
    async def _approve(self, request, gas_price_wei, nonce=None):
        """
        Initiates a transaction to allow a designated spender to use a certain amount of token.
        """
        pass

    @abstractmethod
    async def _transfer(self, request, gas_price_wei, nonce=None):
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
    def on_request_status_update(self, client_request_id, request_status: RequestStatus, tx_receipt: dict,
                                 mined_tx_hash: str = None):
        """
        Called when a request status is changed, usually by `TransactionsStatusPoller`
        """
        request = self._request_cache.get(client_request_id)
        if request:
            if mined_tx_hash:
                request.dex_specific["mined_tx_hash"] = mined_tx_hash
            self._request_cache.finalise_request(client_request_id, request_status)

    @abstractmethod
    async def start(self, private_key=None):
        if self._transactions_status_poller:
            await self._transactions_status_poller.start()

        if self._request_cache:
            await self._request_cache.start(self._transactions_status_poller)

        if "fordefi" in self._config:
            self.__whitelist_manager = WhitelistingManagerFordefi(self.pantheon, self, self._config)
            await self.__whitelist_manager.start()
        elif "fireblocks" in self._config:
            self.__whitelist_manager = WhitelistingManagerFireblocks(self.pantheon, self, self._config)
            await self.__whitelist_manager.start()
        else:
            self._withdrawal_address_whitelists = self._withdrawal_address_whitelists_from_res_file

    def get_request(self, client_request_id) -> Optional[Request]:
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
                   params['request_type'] == 'APPROVE' or params['request_type'] == 'WRAP_UNWRAP', \
                'Unknown request type'
            request_type = RequestType[params['request_type']]

            self._logger.debug(f'Getting all open requests: request_type={request_type.name}')
            return 200, [request.to_dict() for request in self._request_cache.get_all(request_type)]

        except Exception as e:
            self._logger.exception(f'Failed to get all open requests: %r', e)
            return 400, {'error': {'message': str(e)}}

    async def __get_status(self, path, params, received_at_ms):
        if self.started:
            return 200, {"status": "ok"}
        else:
            return 503, {"status": "starting"}

    async def __cancel_request(self, path, params: schemas.CancelRequestParams, received_at_ms):
        try:
            client_request_id = params['client_request_id']
            request = self.get_request(client_request_id)
            if request is None:
                return 404, {'error': {'message': 'request not found'}}

            if request.is_finalised():
                return 400, {'error': {'message': f'Cannot cancel. Request status={request.request_status.name}'}}

            gas_price_wei = params.get('gas_price_wei')
            if gas_price_wei is not None:
                gas_price_set_on_request = True
                gas_price_wei = int(gas_price_wei)
            else:
                gas_price_set_on_request = False
                gas_price_wei = self._get_gas_price(request, priority_fee=PriorityFee.Fast)

            if not gas_price_set_on_request and gas_price_wei is not None:
                if request.request_status == RequestStatus.CANCEL_REQUESTED and \
                        request.used_gas_prices_wei[-1] >= gas_price_wei:
                    return 400, {'error': {'message': f'Cancel with greater than or equal to the '
                                                      f'gas_price_wei={gas_price_wei} already in progress'}}
                # TODO -> For other EVM based chains it might differ
                # replacement transaction should have gas_price at least greater than 10% of the last gas_price used otherwise
                # 'replacement transaction underpriced' error will occur. https://ethereum.stackexchange.com/a/44875
                if len(request.used_gas_prices_wei) > 0:
                    gas_price_wei = max(gas_price_wei, int(1.1 * request.used_gas_prices_wei[-1]))

            ok, reason = self._check_max_allowed_gas_price(gas_price_wei)
            if not ok:
                return 400, {'error': {'message': reason}}

            self._logger.debug(f'Canceling={request}, gas_price_wei={gas_price_wei}')

            result = await self._cancel_transaction(request, gas_price_wei)
            if result.error_type == ErrorType.NO_ERROR:
                request.request_status = RequestStatus.CANCEL_REQUESTED
                if result.tx_hash is not None:
                    request.tx_hashes.append((result.tx_hash, RequestType.CANCEL.name))
                    request.used_gas_prices_wei.append(gas_price_wei)
                    self._transactions_status_poller.add_for_polling(result.tx_hash, client_request_id,
                                                                     RequestType.CANCEL)
                self._request_cache.maybe_add_or_update_request_in_redis(client_request_id)
                if result.pending_task:
                    await result.pending_task
                return 200, {'result': {'tx_hash': result.tx_hash}}
            else:
                cancel_error_response = {'error': {'code': result.error_type.value, 'message': result.error_message}}
                if result.error_type == ErrorType.TRANSACTION_FAILED and 'already mined' in result.error_message:
                    # Chance to cancellation doesn't exist, ES will not reTry cancellations.
                    return 408, cancel_error_response
                else:
                    return 400, cancel_error_response

        except Exception as e:
            self._logger.exception(f'Failed to cancel request: %r', e)
            return 400, {'error': {'message': repr(e)}}

    @abstractmethod
    async def _cancel_all(self, path, params: schemas.CancelAllParams, received_at_ms):
        try:
            assert params['request_type'] == 'ORDER' or params['request_type'] == 'TRANSFER' \
                   or params['request_type'] == 'APPROVE' or params['request_type'] == 'WRAP_UNWRAP', \
                'Unknown transaction type'
            request_type = RequestType[params['request_type']]

            self._logger.debug(f'Canceling all requests, request_type={request_type.name}')

            cancel_requested = []
            failed_cancels = []

            for request in self._request_cache.get_all(request_type):
                try:
                    gas_price_wei = self._get_gas_price(request, priority_fee=PriorityFee.Fast)

                    if request.request_status == RequestStatus.CANCEL_REQUESTED:
                        if gas_price_wei is None:
                            self._logger.info(
                                f'Not sending cancel request for client_request_id={request.client_request_id}'
                                f' as cancel already in progress')
                            cancel_requested.append(request.client_request_id)
                            continue
                        elif request.used_gas_prices_wei[-1] >= gas_price_wei:
                            self._logger.info(
                                f'Not sending cancel request for client_request_id={request.client_request_id} '
                                f'as cancel with greater than or equal to the gas_price_wei={gas_price_wei} already in progress')
                            cancel_requested.append(request.client_request_id)
                            continue

                    if gas_price_wei and len(request.used_gas_prices_wei) > 0:
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
                        if result.tx_hash:
                            request.tx_hashes.append((result.tx_hash, RequestType.CANCEL.name))
                            request.used_gas_prices_wei.append(gas_price_wei)
                            self._transactions_status_poller.add_for_polling(
                                result.tx_hash, request.client_request_id, RequestType.CANCEL)
                        if result.pending_task:
                            await result.pending_task

                        cancel_requested.append(request.client_request_id)
                        self._request_cache.maybe_add_or_update_request_in_redis(request.client_request_id)
                    else:
                        failed_cancels.append(request.client_request_id)
                except Exception as ex:
                    self._logger.exception(f'Failed to cancel request={request.client_request_id}: %r', ex)
                    failed_cancels.append(request.client_request_id)
            return 400 if failed_cancels else 200, {'cancel_requested': cancel_requested,
                                                    'failed_cancels': failed_cancels}

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
            gas_limit = 500000  # TODO: Check for the most suitable value

            ok, reason = self._check_max_allowed_gas_price(gas_price_wei)
            if not ok:
                return 400, {'error': {'message': reason}}

            request = ApproveRequest(client_request_id, symbol, amount, gas_limit, path, received_at_ms,
                                     dex_specific={
                                         'dex': params.get('dex')
                                     })
            self._logger.debug(f'Approving={request}, gas_price_wei={gas_price_wei}')

            self._request_cache.add(request)

            result = await self._approve(request=request, gas_price_wei=gas_price_wei)
            if result.error_type == ErrorType.NO_ERROR:
                request.nonce = result.nonce
                request.tx_hashes.append((result.tx_hash, RequestType.APPROVE.name))
                request.used_gas_prices_wei.append(gas_price_wei)

                self._transactions_status_poller.add_for_polling(
                    result.tx_hash, client_request_id, RequestType.APPROVE)
                self._request_cache.maybe_add_or_update_request_in_redis(client_request_id)
                if result.pending_task:
                    await result.pending_task
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

            transfer = TransferRequest(client_request_id, symbol, amount, address_to, gas_limit, path, received_at_ms,
                                       dex_specific={
                                           'dex': params.get('dex')
                                       })
            self._logger.debug(f'Transferring={transfer}, request_path={path}, gas_price_wei={gas_price_wei}')

            self._request_cache.add(transfer)

            result = await self._transfer(request=transfer, gas_price_wei=gas_price_wei)

            transfer.nonce = result.nonce
            if result.error_type == ErrorType.NO_ERROR:
                transfer.tx_hashes.append((result.tx_hash, RequestType.TRANSFER.name))
                transfer.used_gas_prices_wei.append(gas_price_wei)

                if self._transactions_status_poller:
                    self._transactions_status_poller.add_for_polling(
                        result.tx_hash, client_request_id, RequestType.TRANSFER
                    )

                self._request_cache.maybe_add_or_update_request_in_redis(
                    client_request_id
                )

                if result.pending_task:
                    await result.pending_task

                return 200, {"tx_hash": result.tx_hash}

            else:
                self._request_cache.finalise_request(
                    client_request_id, RequestStatus.FAILED
                )
                return 400, {
                    "error": {
                        "code": result.error_type.value,
                        "message": result.error_message,
                    }
                }

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
                    self._request_cache.maybe_add_or_update_request_in_redis(client_request_id)
                    if result.pending_task:
                        await result.pending_task
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
                f'HIGH ALERT: client_request_id={client_request_id} tried to withdraw unknown token={symbol}')
            return False, f'Unknown token={symbol}'

        assert address_to is not None
        if Web3.to_checksum_address(address_to) not in self._withdrawal_address_whitelists[symbol]:
            self._logger.error(
                f'HIGH ALERT: client_request_id={client_request_id} tried to withdraw token={symbol} '
                f'to unknown address={address_to}')
            return False, f'Unknown withdrawal_address={address_to} for token={symbol}'

        return True, ''

    def _check_max_allowed_gas_price(self, gas_price_wei):
        if gas_price_wei is None:
            return True, ''
        if self.__max_allowed_gas_price_wei is not None and gas_price_wei > self.__max_allowed_gas_price_wei:
            return False, f'gas_price_wei={gas_price_wei} is greater than max_allowed_gas_price_wei' \
                          f'={self.__max_allowed_gas_price_wei}'
        return True, ''

    # If a dex needs API tokens whitelist then that dex should override this method
    # tokens : token_symbol -> (token_id, token_address)
    def _on_tokens_whitelist_refresh(self, tokens: dict):
        return

    def _on_withdrawal_whitelist_refresh(self, withdrawal_address_whitelist: defaultdict):
        self._withdrawal_address_whitelists = self._withdrawal_address_whitelists_from_res_file.copy()
        for symbol in withdrawal_address_whitelist:
            self._withdrawal_address_whitelists[symbol].update(withdrawal_address_whitelist[symbol])

    def assertRequiredFields(self, params: dict, required_fields: list):
        for field in required_fields:
            assert field in params, f'Missing required field: {field}'
