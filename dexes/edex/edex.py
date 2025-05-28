import asyncio
from typing import Any, Dict, Optional, Set, Tuple
from ..dex_common import DexCommon

from pyutils.exchange_connectors import ConnectorType

import dexes.edex.schemas as schemas


import asyncio
from typing import Any, Dict, Optional, Set, Tuple

from pyutils.exchange_connectors import ConnectorType

from ..dex_common import DexCommon
import dexes.edex.schemas as schemas


class Edex(DexCommon):
    CHANNELS = ["ORDER", "TRADE"]

    def __init__(
        self,
        pantheon: Any,
        config: Dict[str, Any],
        server: Any,
        event_sink: Any,
    ):
        super().__init__(pantheon, ConnectorType.Native, config, server, event_sink)
        self._edex_config = config
        self._pending_tasks: Set[asyncio.Task] = set()

        self._server.register(
            "POST",
            "/private/initialize-user",
            self._initialize_user,
            response_model=schemas.InitializeUserResponse,
            summary="Initialize user",
            tags=["private", "edex"],
            oapi_in=["edex"],
        )
        self._server.register(
            "POST",
            "/private/enable-margin-trading",
            self._enable_margin_trading,
            response_model=schemas.UpdateMarginTradingResponse,
            summary="Enable margin trading",
            tags=["private", "edex"],
            oapi_in=["edex"],
        )
        self._server.register(
            "POST",
            "/private/disable-margin-trading",
            self._disable_margin_trading,
            response_model=schemas.UpdateMarginTradingResponse,
            summary="Disable margin trading",
            tags=["private", "edex"],
            oapi_in=["edex"],
        )
        self._server.register(
            "POST",
            "/private/create-order",
            self._create_order,
            request_model=schemas.CreateOrderRequest,
            response_model=schemas.CreateOrderResponse,
            summary="Create a new order",
            tags=["private", "edex"],
            oapi_in=["edex"],
        )
        self._server.register(
            "DELETE",
            "/private/cancel-order",
            self._cancel_order,
            request_model=schemas.CancelOrderParams,
            response_model=schemas.CancelOrderSuccess,
            responses={
                400: {"model": schemas.CancelOrderErrorResponse},
                404: {"model": schemas.CancelOrderErrorResponse},
            },
            summary="Cancel a single order",
            tags=["private", "edex"],
            oapi_in=["edex"],
        )
        self._server.register(
            "DELETE",
            "/private/cancel-all-orders",
            self._cancel_all_orders,
            response_model=schemas.CancelAllOrdersResponse,
            summary="Cancel all orders",
            tags=["private", "edex"],
            oapi_in=["edex"],
        )
        self._server.register(
            "GET",
            "/public/order",
            self._query_order,
            request_model=schemas.QueryOrderParams,
            response_model=schemas.QueryOrderResponse,
            responses={404: {"model": schemas.CancelOrderErrorResponse}},
            summary="Get a single order",
            tags=["public", "edex"],
            oapi_in=["edex"],
        )
        self._server.register(
            "GET",
            "/public/orders",
            self._query_live_orders,
            response_model=schemas.QueryLiveOrdersResponse,
            summary="List live orders",
            tags=["public", "edex"],
            oapi_in=["edex"],
        )
        self._server.register(
            "GET",
            "/public/portfolio",
            self._query_portfolio,
            response_model=schemas.QueryPortfolioResponse,
            summary="Get account portfolio",
            tags=["public", "edex"],
            oapi_in=["edex"],
        )
        self._server.register(
            "POST",
            "/private/deposit-token",
            self._deposit,
            request_model=schemas.DepositRequest,
            response_model=schemas.TxSigResponse,
            responses={
                400: {"model": schemas.DepositErrorResponse},
                500: {"model": schemas.TransactionFailedResponse},
            },
            summary="Deposit tokens into spot account",
            tags=["private", "edex"],
            oapi_in=["edex"],
        )
        self._server.register(
            "POST",
            "/private/withdraw-token",
            self._withdraw,
            request_model=schemas.WithdrawRequest,
            response_model=schemas.TxSigResponse,
            responses={
                400: {"model": schemas.WithdrawErrorResponse},
            },
            summary="Withdraw tokens from spot account",
            tags=["private", "edex"],
            oapi_in=["edex"],
        )
        self._server.register(
            "GET",
            "/public/balance",
            self._get_balance,
            response_model=schemas.BalanceResponse,
            summary="Get spot balances and perp PnL",
            tags=["public", "edex"],
            oapi_in=["edex"],
        )
        self._server.register(
            "GET",
            "/public/contract-data",
            self._get_contract_data,
            response_model=schemas.ContractDataResponse,
            summary="Get per‐contract funding & interest data",
            tags=["public", "edex"],
            oapi_in=["edex"],
        )
        self._server.register(
            "GET",
            "/public/margin-data",
            self._get_margin_data,
            response_model=schemas.MarginDataResponse,
            summary="Get user margin & PnL data",
            tags=["public", "edex"],
            oapi_in=["edex"],
        )
        self._server.register(
            "GET",
            "/public/markets",
            self._fetch_markets,
            response_model=schemas.MarketsResponse,
            summary="List available markets",
            tags=["public", "edex"],
            oapi_in=["edex"],
        )
        self._server.register(
            "GET",
            "/public/transfers",
            self._fetch_transfer_records,
            request_model=schemas.FetchTransferRecordsParams,
            response_model=schemas.TransfersResponse,
            summary="Get transfer records",
            tags=["public", "edex"],
            oapi_in=["edex"],
        )
        self._server.register(
            "GET",
            "/public/funding",
            self._fetch_funding_records,
            request_model=schemas.FetchFundingRecordsParams,
            response_model=schemas.FundingResponse,
            summary="Get funding payment records",
            tags=["public", "edex"],
            oapi_in=["edex"],
        )
        self._server.register(
            "GET",
            "/public/trades",
            self._fetch_trades,
            request_model=schemas.FetchTradesParams,
            response_model=schemas.TradesResponse,
            summary="Get trade records",
            tags=["public", "edex"],
            oapi_in=["edex"],
        )

    async def start(self, some_pk: str) -> None:
        await super().start(some_pk)
        self.started = True

    async def on_request_status_update(
        self,
        client_request_id: Any,
        request_status: Any,
        tx_receipt: Dict[str, Any],
        mined_tx_hash: Optional[str] = None,
    ) -> None:
        pass

    async def _initialize_user(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        return 200, schemas.InitializeUserResponse.model_config["json_schema_extra"]["examples"]["success"]

    async def _enable_margin_trading(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        return 200, schemas.UpdateMarginTradingResponse.model_config["json_schema_extra"]["examples"]["enable_success"]

    async def _disable_margin_trading(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        return 200, schemas.UpdateMarginTradingResponse.model_config["json_schema_extra"]["examples"]["disable_success"]

    async def _create_order(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        return 200, schemas.CreateOrderResponse.model_config["json_schema_extra"]["examples"]["create_success"]

    async def _cancel_order(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        return 200, schemas.CancelOrderSuccess.model_config["json_schema_extra"]["example"]

    async def _cancel_all_orders(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        return 200, schemas.CancelAllOrdersResponse.model_config["json_schema_extra"]["example"]

    async def _query_order(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        return 200, schemas.QueryOrderResponse.model_config["json_schema_extra"]["example"]  # type: ignore

    async def _query_live_orders(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        return 200, schemas.QueryLiveOrdersResponse.model_config["json_schema_extra"]["example"]  # type: ignore

    async def _query_portfolio(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        return 200, schemas.QueryPortfolioResponse.model_config["json_schema_extra"]["example"]

    async def _deposit(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        return 200, schemas.TxSigResponse.model_config["json_schema_extra"]["example"]

    async def _withdraw(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        return 200, schemas.TxSigResponse.model_config["json_schema_extra"]["example"]

    async def _get_balance(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        return 200, schemas.BalanceResponse.model_config["json_schema_extra"]["example"]

    async def _get_contract_data(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        return 200, schemas.ContractDataResponse.model_config["json_schema_extra"]["example"]

    async def _get_margin_data(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        return 200, schemas.MarginDataResponse.model_config["json_schema_extra"]["example"]

    async def _fetch_markets(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        return 200, schemas.MarketsResponse.model_config["json_schema_extra"]["example"]

    async def _fetch_transfer_records(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        return 200, schemas.TransfersResponse.model_config["json_schema_extra"]["example"]

    async def _fetch_funding_records(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        return 200, schemas.FundingResponse.model_config["json_schema_extra"]["example"]

    async def _fetch_trades(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        return 200, schemas.TradesResponse.model_config["json_schema_extra"]["example"]


    # these need a schema for the parent class
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
        return 200, {"requests": []}

    async def _cancel_all(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
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
        return 200, {"requests": []}

    async def _cancel_all(
        self, path: str, params: Dict[str, Any], received_at_ms: int
    ) -> Tuple[int, Dict[str, Any]]:
        return 200, {"message": "cancel-all stub"}

    async def on_new_connection(self, ws: Any) -> None:
        pass

    async def process_request(
        self, ws: Any, request_id: Any, method: str, params: Dict[str, Any]
    ) -> None:
        pass
    async def _transfer(
         self, request, gas_price_wei: int, nonce: int=None,
     ) -> bool:
        pass
