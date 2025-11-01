import logging
import inspect

from .gte_api import GteApi
from pantheon.timestamp_ns import TimestampNs
from typing import Any, Dict, Optional, Tuple
from web3 import AsyncWeb3
from gte_py.clients import Client
from gte_py.configs import TESTNET_CONFIG
from gte_py.api.chain.utils import make_web3
from eth_utils import to_checksum_address

import py_dex_common.schemas as schemas
from py_dex_common.dexes.dex_common import DexCommon

_logger = logging.getLogger('gte')

class Gte(DexCommon):
    CHANNELS = ["ORDER", "TRADE"]

    def __init__(
        self,
        pantheon: Any,
        config: Dict[str, Any],
        server: Any,
        event_sink: Any,
    ):
        super().__init__(pantheon, config, server, event_sink)
        self._gte_config = config
        self.__is_readonly = self._gte_config['is_readonly']
        
        self.__wallet_address = to_checksum_address(self._gte_config['wallet_address'])
        self.__client: Client | None = None
        self.__api: GteApi | None = None
        
        self._server.register(
            "POST",
            "/private/create-order",
            self._create_order,
            request_model=schemas.CreateOrderRequest,
            response_model=schemas.CreateOrderResponse,
            summary="Create a new order",
            tags=["private"],
            oapi_in=["gte"],
        )
        self._server.register(
            "DELETE",
            "/private/cancel-order",
            self._cancel_order,
            request_model=schemas.CancelOrderParams,
            response_model=schemas.CancelOrderSuccess,
            response_errors={
                400: {"model": schemas.CancelOrderErrorResponse},
                404: {"model": schemas.CancelOrderErrorResponse},
            },
            summary="Cancel a single order",
            tags=["private"],
            oapi_in=["gte"],
        )
        self._server.register(
            "DELETE",
            "/private/cancel-all-orders",
            self._cancel_all_orders,
            response_model=schemas.CancelAllOrdersResponse,
            summary="Cancel all orders",
            tags=["private"],
            oapi_in=["gte"],
        )
        self._server.register(
            "GET",
            "/public/order",
            self.__get_order,
            request_model=schemas.QueryOrderParams,
            response_model=schemas.QueryOrderResponse,
            response_errors={404: {"model": schemas.CancelOrderErrorResponse}},
            summary="Get a single order",
            tags=["public"],
            oapi_in=["gte"],
        )
        self._server.register(
            "GET",
            "/public/balance",
            self.__get_balance,
            response_model=schemas.BalanceResponse,
            summary="Get spot balances and perp PnL",
            tags=["public"],
            oapi_in=["gte"],
        )
        self._server.register(
            "GET",
            "/public/instrument-data",
            self.__get_instrument_data,
            response_model=schemas.InstrumentDataResponse,
            summary="Get instrument mark price, funding & interest data",
            tags=["public"],
            oapi_in=["gte"],
        )
        self._server.register(
            "GET",
            "/public/instrument-definitions",
            self.__get_instrument_definitions,
            response_model=schemas.InstrumentDefinitionDataResponse,
            summary="Get instrument defintions",
            tags=["public"],
            oapi_in=["gte"],
        )
        self._server.register(
            "GET",
            "/public/margin",
            self.__get_margin,
            response_model=schemas.MarginDataResponse,
            summary="Get user margin & PnL data",
            tags=["public"],
            oapi_in=["gte"],
        )
        self._server.register(
            "GET",
            "/public/transfers",
            self.__get_transfers,
            request_model=schemas.GetTransfersRequest,
            response_model=schemas.TransfersResponse,
            summary="Get transfer records",
            tags=["public"],
            oapi_in=["gte"],
        )
        self._server.register(
            "GET",
            "/public/other-movements",
            self.__get_other_movements,
            request_model=schemas.GetOtherMovementsRequest,
            response_model=schemas.OtherMovementsResponse,
            summary="Get other movements",
            tags=["public"],
            oapi_in=["gte"],
        )
        self._server.register(
            "GET",
            "/public/trades",
            self.__get_trades,
            request_model=schemas.GetTradesRequest,
            response_model=schemas.TradesResponse,
            summary="Get trade records",
            tags=["public"],
            oapi_in=["gte"],
        )

    async def start(self, private_key: str) -> None:
        await super().start(private_key)
        
        network = TESTNET_CONFIG
        
        if not self.__is_readonly:
            web3 = await make_web3(network, self.__wallet_address, private_key)
            self.__client = Client(web3=web3, config=network, account=self.__wallet_address)
            
            await self.__client.init()
        else:
            web3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(network.rpc_http))
            self.__client = Client(web3=web3, config=network)
        
        self.__api = GteApi(self.pantheon, client=self.__client, event_sink=self._event_sink, wallet_address=self.__wallet_address)
        await self.__api.start()
        
        self.started = True

    async def on_request_status_update(
        self,
        client_request_id: Any,
        request_status: Any,
        tx_receipt: Dict[str, Any],
        mined_tx_hash: Optional[str] = None,
    ) -> None:
        pass

    # Generic API 
    async def _create_order(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        _logger.debug(f"_create_order {inspect.currentframe().f_code.co_name}] "
            f"received_at_ms={received_at_ms}, path={path}, params={params}")
        raise NotImplementedError("not implemented yet")

    async def _cancel_order(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        _logger.debug(f"_cancel_order {inspect.currentframe().f_code.co_name}] "
            f"received_at_ms={received_at_ms}, path={path}, params={params}")
        raise NotImplementedError("not implemented yet")

    async def _cancel_all_orders(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        _logger.debug(f"_cancel_all_orders {inspect.currentframe().f_code.co_name}] "
            f"received_at_ms={received_at_ms}, path={path}, params={params}")
        raise NotImplementedError("not implemented yet")

    async def __get_order(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        _logger.debug(f"_query_order {inspect.currentframe().f_code.co_name}] "
            f"received_at_ms={received_at_ms}, path={path}, params={params}")
        raise NotImplementedError("not implemented yet")
    
    async def __get_balance(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        _logger.debug(f"_get_balance {inspect.currentframe().f_code.co_name}] "
            f"received_at_ms={received_at_ms}, path={path}, params={params}")

        return 200, await self.__api.get_balance()

    async def __get_instrument_data(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        _logger.debug(f"_get_instrument_data {inspect.currentframe().f_code.co_name}] "
            f"received_at_ms={received_at_ms}, path={path}, params={params}")
        return 200, await self.__api.get_instrument_data()
    
    async def __get_instrument_definitions(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        _logger.debug(f"_get_instrument_definitions {inspect.currentframe().f_code.co_name}] "
            f"received_at_ms={received_at_ms}, path={path}, params={params}")
        include_raw = params.get("include_raw")

        return 200, await self.__api.get_instrument_definitions(include_raw)

    async def __get_margin(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        _logger.debug(f"_get_margin_data {inspect.currentframe().f_code.co_name}] "
            f"received_at_ms={received_at_ms}, path={path}, params={params}")
        return 200, self.__api.get_margin()

    async def __get_transfers(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        _logger.debug(f"_fetch_transfer_records {inspect.currentframe().f_code.co_name}] "
            f"received_at_ms={received_at_ms}, path={path}, params={params}")
        return 200, self.__api.get_transfers()

    async def __get_other_movements(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        _logger.debug(f"__get_other_movements {inspect.currentframe().f_code.co_name}] "
            f"received_at_ms={received_at_ms}, path={path}, params={params}")
        return 200, await self.__api.get_other_movements()

    async def __get_trades(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        _logger.debug(f"_fetch_trades {inspect.currentframe().f_code.co_name}] "
            f"received_at_ms={received_at_ms}, path={path}, params={params}")
        start_timestamp = TimestampNs.from_ns_since_epoch(int(params.get("start_timestamp")))
        end_timestamp = TimestampNs.from_ns_since_epoch(int(params.get("end_timestamp")))
        client_order_id = params.get("client_order_id")
        include_raw = params.get("include_raw")

        return 200, await self.__api.get_trades(start_timestamp, end_timestamp, client_order_id, include_raw)

    # Implementations from base class
    async def _approve(
        self, request: Any, gas_price_wei: int, nonce: Optional[int] = None
    ) -> Any:
        raise NotImplementedError("approve stub")

    async def _amend_transaction(
        self, request: Any, params: Dict[str, Any], gas_price_wei: int
    ) -> Any:
        raise NotImplementedError("amend-transaction stub")

    async def _cancel_transaction(
        self, request: Any, gas_price_wei: int
    ) -> Any:
        raise NotImplementedError("cancel-transaction stub")

    async def get_transaction_receipt(
        self, request: Any, tx_hash: str
    ) -> Any:
        raise NotImplementedError("get-transaction-receipt stub")

    def _get_gas_price(
        self, request: Any, priority_fee: Any
    ) -> Any:
        raise NotImplementedError("get-gas-price stub")
    
    async def _get_all_open_requests(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        _logger.debug(f"test {inspect.currentframe().f_code.co_name}] "
            f"received_at_ms={received_at_ms}, path={path}, params={params}")
        return 200, {"requests": []}

    async def _cancel_all(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        _logger.debug(f"test {inspect.currentframe().f_code.co_name}] "
            f"received_at_ms={received_at_ms}, path={path}, params={params}")
        return 200, {"message": "cancel-all stub"}

    async def on_new_connection(self, ws: Any) -> None:
        pass

    async def process_request(
        self, ws: Any, request_id: Any, method: str, params: Dict[str, Any]
    ) -> None:
        pass

    async def _transfer(
        self, request: Any, gas_price_wei: int, nonce: Optional[int] = None
    ) -> bool:
        pass
