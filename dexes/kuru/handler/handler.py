import logging
import time
import asyncio
from multiprocessing import Lock
from typing import Optional, cast, Dict, List, Tuple, Union
from dataclasses import dataclass

from aiohttp import web
from eth_account import Account
from kuru_sdk import ClientOrderExecutor, TxOptions
from web3 import AsyncHTTPProvider, AsyncWeb3, Web3, HTTPProvider

from schemas import OrderResponse, CreateOrderRequest, QueryLiveOrdersResponse, OrderErrorResponse, \
    CancelAllOrdersResponse
from schemas.cancel_orders import CancelAllOrdersErrorResponse

from .schemas import CreateOrderOut, ErrorCode, OrderStatus, OrderIn, CancelOrderIn
from .validators import ValidationError, validate_and_map_to_kuru_order_request, validate_order_request
from .pantheon_utils import get_current_timestamp_ns
from .web3_request_manager import Web3RequestManager
from .ws_order_manager import WsOrderManager


@dataclass
class OrderCompletion:
    event: asyncio.Event
    result_status: Optional[int] = None
    
    def __init__(self):
        self.event = asyncio.Event()
        self.result_status = None


class KuruHandler:
    def __init__(self, config: dict):
        self._config = config
        self._private_key = None
        
        self._order_completions: Dict[str, OrderCompletion] = {}
        self._orders_cache: Dict[str, OrderResponse] = {}
        self._clients: Dict[str, ClientOrderExecutor] = {}
        # TODO: Probably Dict[str, str] will be better
        self._client_to_order_id_map: Dict[str, int] = {}  # client_order_id -> order_id

        self._logger = logging.getLogger(__name__)
        
        self.nonce_manager: Optional[Web3RequestManager] = None

    async def start(self, private_key):
        self._private_key = private_key

        self.nonce_manager = await self._init_nonce_manager()

    async def orders(self, path, params, received_at_ms) -> Tuple[int, QueryLiveOrdersResponse]:
        """Get all orders with OPEN status from cache"""
        open_orders = [
            order for order in self._orders_cache.values() 
            if order.status == OrderStatus.OPEN
        ]
        return 200, QueryLiveOrdersResponse(
            send_timestamp_ns=get_current_timestamp_ns(),
            orders=open_orders
        )

    async def order(self, path, params, received_at_ms) -> Tuple[int, OrderResponse | dict]:
        """Get a single order from cache by client_order_id"""
        order_input = cast(OrderIn, params)
        try:
            client_order_id = validate_order_request(order_input)
        except ValidationError as e:
            self._logger.exception("Error validating order request")

            # TODO: add error respnose object
            return 400, {
                "error_code": ErrorCode.INVALID_PARAMETER,
                "error_message": f"Input params are invalid: {', '.join(e.args[0])}",
            }
        
        if client_order_id in self._orders_cache:
            return 200, self._orders_cache[client_order_id]
        else:
            # TODO: add error response object
            return 404, {
                "error_code": ErrorCode.ORDER_NOT_FOUND,
                "error_message": f"Order with client_order_id {client_order_id} not found"
            }

    def get_order_completions(self) -> Dict[str, OrderCompletion]:
        return self._order_completions

    async def clear(self) -> None:
        self._order_completions.clear()
        self._orders_cache.clear()
        self._client_to_order_id_map.clear()
        
        for client in self._clients.values():
            await client.stop_tx_processor()
        self._clients.clear()
        
        if self.nonce_manager is not None:
            self._logger.info(f"Stopping nonce manager for {self._config['url']} ...")
            await self.nonce_manager.stop()
            self._logger.info(f"Nonce manager stopped for {self._config['url']}. Removing reference")
            self.nonce_manager = None

    def cleanup_order_completion(self, client_order_id: str) -> None:
        if client_order_id in self._order_completions:
            del self._order_completions[client_order_id]

    async def on_create_order_transaction_completed(self, tx_receipt, external_client_order_id: str, orderbook_address: str) -> None:
        if external_client_order_id in self._orders_cache:
            if tx_receipt.status == 1:
                # Extract order_id from receipt
                client = self._clients.get(orderbook_address)
                if client:
                    order_id = client.orderbook.get_order_id_from_receipt(tx_receipt)
                    if order_id is not None:
                        self._orders_cache[external_client_order_id].order_id = str(order_id)
                        self._client_to_order_id_map[external_client_order_id] = order_id
            else:
                self._orders_cache[external_client_order_id].status = OrderStatus.REJECTED
            self._orders_cache[external_client_order_id].last_update_timestamp_ns = get_current_timestamp_ns()

        if external_client_order_id in self._order_completions:
            completion = self._order_completions[external_client_order_id]
            completion.result_status = tx_receipt.status
            completion.event.set()

        self._logger.info(f"Received order transaction completed {external_client_order_id} for market {orderbook_address}, status: {tx_receipt.status}")

    async def create_order(self, path, params, received_at_ms) -> Tuple[int, Union[OrderResponse, OrderErrorResponse]]:
        order_input = CreateOrderRequest(**params)
        try:
            order_request = validate_and_map_to_kuru_order_request(order_input)
        except ValidationError as e:
            self._logger.error(e)
            return 400, OrderErrorResponse(
                error_code=ErrorCode.INVALID_PARAMETER,
                error_message=f"Input params are invalid: {', '.join(e.args[0])}"
            )

        web3 = await self._create_web3()
        client = await self._create_client_order_executor(order_request.market_address, web3)
        
        start_time = time.time()
        self._logger.info(f"Placing limit buy order, order_request: {order_request}")

        kuru_cloid = ""
        tx_hash = ""
        client_order_id = order_input.client_order_id
        
        try:
            # Create the completion tracking for this order before placing it
            self._order_completions[client_order_id] = OrderCompletion()
            callback_args = (client_order_id, order_request.market_address)

            nonce_ = await self.nonce_manager.get_nonce()
            self._logger.info(f"Using nonce {nonce_}")
            kuru_cloid = await client.place_order(
                order_request, 
                async_execution=True, 
                callback=self.on_create_order_transaction_completed,
                callback_args=callback_args,
                tx_options=TxOptions(
                    nonce=nonce_
                )
            )

            assert kuru_cloid is not None
            assert len(kuru_cloid) > 0
            
            tx_hash = kuru_cloid.split("_")[0]
        except Exception as ex:
            self._logger.error("Failed to insert order", ex)
            self.cleanup_order_completion(client_order_id)
            return 400, OrderErrorResponse(
                error_code=ErrorCode.EXCHANGE_REJECTION,
                error_message=f"failed to insert order {order_input.client_order_id}. Reason: {ex}"
            )

        end_time = time.time()
        duration = end_time - start_time

        self._logger.info(
            f"Order placed successfully by orig SDK, kuru_cloid: {kuru_cloid}, duration: {duration:.4f}"
        )

        response = OrderResponse(
            client_order_id=order_input.client_order_id,
            order_id="",
            price=order_request.price or "0",
            quantity=order_request.size or "0",
            total_exec_quantity="0",
            last_update_timestamp_ns=get_current_timestamp_ns(),
            status=OrderStatus.OPEN,
            trades=[],
            order_type=order_input.order_type,
            symbol=order_input.symbol,
            side=order_input.side,
            send_timestamp_ns=get_current_timestamp_ns(),
            place_tx_id=tx_hash,
            reason=""
        )
        
        self._orders_cache[client_order_id] = response
        
        now = time.time()
        self._logger.info(f"Received order: {path}, {params}, {received_at_ms}, {now}")
        return 200, response

    async def cancel_order(self, path, params, received_at_ms) \
            -> Tuple[int, Union[OrderErrorResponse, List[OrderResponse]]]:
        """Cancel a single order by client_order_id"""
        cancel_order_input = cast(CancelOrderIn, params)
        
        status_code, error_response, validated_data = await self._validate_cancel_order_request(cancel_order_input)
        if status_code is not None:
            return status_code, error_response
        
        assert validated_data is not None
        client_order_id, order_id, order = validated_data

        market_address = order.symbol
        web3 = await self._create_web3()
        client = await self._create_client_order_executor(market_address, web3)
        
        # 6. Cancel the order
        try:
            nonce = await self.nonce_manager.get_nonce()
            tx_options = TxOptions(nonce=nonce)
            tx_hash = await client.cancel_orders(
                market_address=market_address,
                order_ids=[order_id],
                tx_options=tx_options
            )
            
            order.last_update_timestamp_ns = get_current_timestamp_ns()
            order.status = OrderStatus.CANCELLED_PENDING
            
            self._logger.info(f"Transaction for order cancelling was sent successfully, client_order_id: {client_order_id}, order_id: {order_id}, tx_hash: {tx_hash}")
            
            return 200, order
            
        except Exception as ex:
            self._logger.error(f"Failed to cancel order {client_order_id}", exc_info=ex)
            return 400, OrderErrorResponse(
                error_code=ErrorCode.EXCHANGE_REJECTION,
                error_message=f"Failed to cancel order {client_order_id}. Reason: {ex}"
            )

    async def cancel_all_orders(self, path, params, received_at_ms) \
            -> Tuple[int, Union[CancelAllOrdersErrorResponse, CancelAllOrdersResponse]]:
        """Cancel all OPEN orders"""
        cancelled_orders_ids = []
        errors = []
        
        orders_by_market = self._group_orders_by_market()
        
        web3 = await self._create_web3()
        
        for market_address, order_list in orders_by_market.items():
            try:
                client = await self._create_client_order_executor(market_address, web3)
                order_ids = [order_id for _, order_id in order_list]
                
                nonce = await self.nonce_manager.get_nonce()
                tx_options = TxOptions(nonce=nonce)
                tx_hash = await client.cancel_orders(
                    market_address=market_address,
                    order_ids=order_ids,
                    tx_options=tx_options
                )
                
                # Update order statuses
                for client_order_id, _ in order_list:
                    self._orders_cache[client_order_id].status = OrderStatus.CANCELLED_PENDING
                    self._orders_cache[client_order_id].last_update_timestamp_ns = get_current_timestamp_ns()
                    cancelled_orders_ids.append(client_order_id)
                
                self._logger.info(f"Cancelled {len(order_ids)} orders for market {market_address}, tx_hash: {tx_hash}")
                
            except Exception as ex:
                self._logger.error(f"Failed to cancel orders for market {market_address}", exc_info=ex)
                errors.append(f"Market {market_address}: {str(ex)}")
        
        if errors:
            return 400, CancelAllOrdersErrorResponse(
                error_code=ErrorCode.EXCHANGE_REJECTION,
                error_message=f"Some orders failed to cancel: {'; '.join(errors)}",
                cancelled=cancelled_orders_ids
            )
        
        return 200, CancelAllOrdersResponse(
            cancelled=cancelled_orders_ids,
            send_timestamp_ns=get_current_timestamp_ns()
        )

    def _group_orders_by_market(self):
        orders_by_market: Dict[str, List[Tuple[str, int]]] = {}  # market -> [(client_order_id, order_id)]
        
        for client_order_id, order in self._orders_cache.items():
            if order.status == OrderStatus.OPEN:
                order_id = self._client_to_order_id_map.get(client_order_id)
                if order_id is not None:
                    market = order.symbol
                    if market not in orders_by_market:
                        orders_by_market[market] = []
                    orders_by_market[market].append((client_order_id, order_id))
        return orders_by_market



    async def _validate_cancel_order_request(self, cancel_order_input: CancelOrderIn) \
            -> Tuple[Optional[int], Optional[OrderErrorResponse], Optional[Tuple[str, int, OrderResponse]]]:
        try:
            client_order_id = validate_order_request(cancel_order_input)
        except ValidationError as e:
            self._logger.error(e)
            return 400, OrderErrorResponse(
                error_code=ErrorCode.INVALID_PARAMETER,
                error_message=f"Input params are invalid: {', '.join(e.args[0])}"
            ), None

        if client_order_id not in self._orders_cache:
            return 404, OrderErrorResponse(
                error_code=ErrorCode.ORDER_NOT_FOUND,
                error_message=f"Order with client_order_id {client_order_id} not found"
            ), None

        order_id = self._client_to_order_id_map.get(client_order_id)
        if order_id is None:
            return 404, OrderErrorResponse(
                error_code=ErrorCode.ORDER_NOT_FOUND,
                error_message=f"Order ID not found for client_order_id {client_order_id}"
            ), None

        order = self._orders_cache[client_order_id]
        if order.status != OrderStatus.OPEN:
            return 400, OrderErrorResponse(
                error_code=ErrorCode.INVALID_PARAMETER,
                error_message=f"Order with client_order_id {client_order_id} is not open (status: {order.status})"
            ), None

        return None, None, (client_order_id, order_id, order)


    async def _create_client_order_executor(self, market_address: str, web3: Web3) -> ClientOrderExecutor:
        if market_address not in self._clients:
            client = ClientOrderExecutor(
                web3=web3,
                contract_address=market_address,
                private_key=self._private_key,
            )
            self._clients[market_address] = client

            await WsOrderManager.ensure_instance(market_address, self._config["ws_url"], self._private_key, client.orderbook.market_params)
        return self._clients[market_address]

    async def _create_web3(self) -> Web3:
        web3 = Web3(HTTPProvider(
            endpoint_uri=self._config["url"],
            #cacheable_requests={"eth_chainId"},
            #cache_allowed_requests=True
        ))
        return web3
    
    async def _init_nonce_manager(self) -> Web3RequestManager:
        if self.nonce_manager is None:
            self._logger.info(f"Initializing new nonce manager for {self._config['url']}")
            async_web3 = AsyncWeb3(AsyncHTTPProvider(self._config["url"]))
            key = Account.from_key(self._private_key)
            await Web3RequestManager.clear_instance(key)
            self.nonce_manager = await Web3RequestManager.ensure_instance(
                web3=async_web3, account=key
            )
            assert self.nonce_manager is not None
        
        return self.nonce_manager


class KuruHandlerSingleton:
    _instance: Optional[KuruHandler] = None
    _lock = Lock()

    @classmethod
    def get_instance(cls, config: dict) -> KuruHandler:
        if cls._instance is None:
            with cls._lock:
                # Double-check pattern
                if cls._instance is None:
                    cls._instance = KuruHandler(config)
        return cls._instance

    @classmethod
    async def reset_instance(cls, handler: Optional[KuruHandler] = None) -> None:
        """Reset the singleton instance. If handler is None, clears the instance."""
        with cls._lock:
            if cls._instance is not None:
                await cls._instance.clear()
            cls._instance = handler