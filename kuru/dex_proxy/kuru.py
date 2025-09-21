from typing import Tuple, Union

from pantheon import Pantheon
from pyutils.exchange_apis.dex_common import RequestStatus
from pyutils.exchange_connectors import ConnectorType
from pyutils.gas_pricing.eth import PriorityFee

from py_dex_common.dexes.dex_common import DexCommon
from .handler.handler import KuruHandlerSingleton
from py_dex_common.web_server import WebServer
import py_dex_common.schemas as schemas



class Kuru(DexCommon):


    CHANNELS = ["ORDER", "TRADE"]

    def __init__(self, pantheon: Pantheon, config: dict, server: WebServer, event_sink):
        super().__init__(pantheon, config, server, event_sink)

        self._kuru_handler = KuruHandlerSingleton.get_instance(config)

        self._server.register(
            "POST",
            "/private/create-order",
            self._kuru_handler.create_order,
            request_model=schemas.CreateOrderRequest,
            response_model=schemas.OrderResponse,
            response_errors={
                400: {"model": schemas.OrderErrorResponse},
            },
            summary="Create a new order",
            tags=["private", "orders"],
            oapi_in=["kuru"],
        )

        self._server.register(
            "DELETE",
            "/private/cancel-order",
            self._kuru_handler.cancel_order,
            request_model=schemas.CancelOrderParams,
            response_model=schemas.OrderResponse,
            response_errors={
                400: {"model": schemas.OrderErrorResponse},
                404: {"model": schemas.OrderErrorResponse},
            },
            summary="Cancel a single order",
            tags=["private", "orders"],
            oapi_in=["kuru"],
        )

        #server.register("DELETE", "/private/cancel-all-orders", self._kuru_handler.cancel_all_orders)
        self._server.register(
            "DELETE",
            "/private/cancel-all-orders",
            self._kuru_handler.cancel_all_orders,
            response_model=schemas.CancelAllOrdersResponse,
            response_errors={
                400: {"model": schemas.CancelAllOrdersErrorResponse},
            },
            summary="Cancel all orders",
            tags=["private", "orders"],
            oapi_in=["kuru"],
        )

        self._server.register(
            "GET",
            "/public/order",
            self._kuru_handler.order,
            request_model=schemas.QueryOrderParams,
            response_model=schemas.OrderResponse,
            response_errors={
                400: {"model": schemas.OrderErrorResponse},
                404: {"model": schemas.OrderErrorResponse},
            },
            summary="Get a single order",
            tags=["public", "orders"],
            oapi_in=["kuru"],
        )

        self._server.register(
            "GET",
            "/public/orders",
            self._kuru_handler.orders,
            response_model=schemas.QueryLiveOrdersResponse,
            summary="List live orders",
            tags=["public", "orders"],
            oapi_in=["kuru"],
        )

        self._server.register(
            "GET",
            "/public/balance",
            self._kuru_handler.balance,
            response_model=schemas.BalanceResponse,
            response_errors={
                400: {"model": schemas.OrderErrorResponse},
            },
            summary="Get wallet and exchange wallet balances",
            tags=["public", "balance"],
            oapi_in=["kuru"],
        )

        self._server.register(
            "GET",
            "/public/margin",
            self._kuru_handler.margin,
            response_model=schemas.MarginDataResponse,
            response_errors={
                400: {"model": schemas.OrderErrorResponse},
            },
            summary="Get margin account data",
            tags=["public", "margin"],
            oapi_in=["kuru"],
        )

        self._server.register(
            "POST",
            "/private/deposit",
            self._kuru_handler.deposit,
            response_errors={
                400: {"model": schemas.OrderErrorResponse},
            },
            summary="Deposit funds to margin account",
            tags=["private", "margin"],
            oapi_in=["kuru"],
        )

        self._server.register(
            "POST",
            "/private/withdraw",
            self._kuru_handler.withdraw,
            response_errors={
                400: {"model": schemas.OrderErrorResponse},
            },
            summary="Withdraw funds from margin account to wallet",
            tags=["private", "margin"],
            oapi_in=["kuru"],
        )


    async def start(self, private_key = None):
        """
        This method is called during a dex_proxy instance run process
        :param private_key:
        :return:
        """
        await self._kuru_handler.start(private_key)

    #
    # Abstract class methods implementation
    #
    #
    async def on_new_connection(self, ws):
        """
        Callback when a WebSocket new connection is established.

        :param ws:
        :return:
        """
        pass

    async def process_request(self, ws, request_id, method, params: dict):
        """
        Callback when a WebSocket message is received.

        :param ws:
        :param request_id:
        :param method:
        :param params:
        :return:
        """
        pass

    async def _approve(self, request, gas_price_wei, nonce=None):
        """

        dexes.dex_common.DexCommon.__approve_token - /private/approve-token handler
        dexes.dex_common.DexCommon._approve
        :param request:
        :param gas_price_wei:
        :param nonce:
        :return:
        """
        pass

    async def _transfer(self, request, gas_price_wei, nonce=None):
        """
        dexes.dex_common.DexCommon.transfer - /private/withdraw handler
        :param request:
        :param gas_price_wei:
        :param nonce:
        :return:
        """
        pass

    async def _amend_transaction(self, request, params, gas_price_wei):
        """
        dexes.dex_common.DexCommon.__amend_request - /private/amend-request handler
        :param request:
        :param params:
        :param gas_price_wei:
        :return:
        """
        pass

    async def _cancel_transaction(self, request, gas_price_wei):
        """
        dexes.dex_common.DexCommon.__cancel_request - /private/cancel-request handler
        dexes.dex_common.DexCommon._cancel_all - /private/cancel-all handler
        :param request:
        :param gas_price_wei:
        :return:
        """
        pass

    async def get_transaction_receipt(self, request, tx_hash):
        """
        This method is used by transaction status poller

        dexes.transactions_status_poller.TransactionsStatusPoller.__poll_tx_hash

        :param request:
        :param tx_hash:
        :return:
        """
        pass

    def _get_gas_price(self, request, priority_fee: PriorityFee):
        """
        Used in cancel routes

        dexes.dex_common.DexCommon.__cancel_request
        dexes.dex_common.DexCommon._cancel_all
        :param request:
        :param priority_fee:
        :return:
        """
        pass

    def on_request_status_update(self, client_request_id, request_status: RequestStatus, tx_receipt: dict, mined_tx_hash: str = None):
        """
        Called when a request status is changed, usually by `TransactionsStatusPoller`
        """
        pass

    async def _get_all_open_requests(self, path, params, received_at_ms):
        """
        Parent dexes.dex_common.DexCommon._get_all_open_requests method is a handler for /public/get-all-open-requests

        :param path:
        :param params:
        :param received_at_ms:
        :return:
        """
        pass

    async def _cancel_all(self, path, params, received_at_ms):
        """
        Parent dexes.dex_common.DexCommon._cancel_all method is a handler for /private/cancel-all

        :param path:
        :param params:
        :param received_at_ms:
        :return:
        """
        pass

