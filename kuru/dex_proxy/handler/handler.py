import asyncio
import logging
import math
import time
from dataclasses import dataclass
from multiprocessing import Lock
from decimal import Decimal
from typing import Optional, Dict, List, Tuple, Union

from eth_account import Account
from kuru_sdk import ClientOrderExecutor, TxOptions, MarginAccount
from py_dex_common.schemas import OrderResponse, CreateOrderRequest, QueryLiveOrdersResponse, OrderErrorResponse, \
    CancelAllOrdersResponse, CancelOrderParams, QueryOrderParams, BalanceResponse
from py_dex_common.schemas.balance import BalanceItem
from py_dex_common.schemas.cancel_orders import CancelAllOrdersErrorResponse
from eth_typing import HexStr
from eth_utils.currency import from_wei, to_wei
from web3 import AsyncHTTPProvider, AsyncWeb3, Web3, HTTPProvider
from .pantheon_utils import get_current_timestamp_ns
from .schemas import ErrorCode, OrderStatus, kuru_order_status_to_common, kuru_error_code_to_common
from .validators import ValidationError, validate_and_map_to_kuru_order_request, validate_order_request
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
        self._margin_contract_addr = "0x4B186949F31FCA0aD08497Df9169a6bEbF0e26ef"
        self._margin_account: Optional[MarginAccount] = None
        # TODO: Read token configurations from resources/ directory
        # This should include token addresses, decimals, symbols, and other metadata
        self._common_tokens = {
            "MON": {
                "address": "0x0000000000000000000000000000000000000000",  # Native token (MON)
                "decimals": 18,
                "symbol": "MON"
            },
            "USDC": {
                "address": "0xf817257fed379853cDe0fa4F97AB987181B1E5Ea",  # USDC token
                "decimals": 6,
                "symbol": "USDC"
            }
        }
        
        # Initialize ERC20 ABI for token balance queries
        self._erc20_abi = [
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function",
            }
        ]

    async def start(self, private_key):
        self._private_key = private_key

        self.nonce_manager = await self._init_nonce_manager()
        self._margin_account = await self._init_margin_account()

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
        order_input = QueryOrderParams(**params)
        try:
            client_order_id = validate_order_request(order_input)
        except ValidationError as e:
            self._logger.exception("Error validating order request")

            # TODO: add error respnose object
            return 400, {
                "error_code": kuru_error_code_to_common(ErrorCode.INVALID_PARAMETER),
                "error_message": f"Input params are invalid: {', '.join(e.args[0])}",
            }
        
        if client_order_id in self._orders_cache:
            return 200, self._orders_cache[client_order_id]
        else:
            # TODO: add error response object
            return 404, {
                "error_code": kuru_error_code_to_common(ErrorCode.ORDER_NOT_FOUND),
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
                error_code=kuru_error_code_to_common(ErrorCode.INVALID_PARAMETER),
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
            status=kuru_order_status_to_common(OrderStatus.OPEN),
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
        cancel_order_input = CancelOrderParams(**params)
        
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



    async def _validate_cancel_order_request(self, cancel_order_input: CancelOrderParams) \
            -> Tuple[Optional[int], Optional[OrderErrorResponse], Optional[Tuple[str, int, OrderResponse]]]:
        try:
            client_order_id = validate_order_request(cancel_order_input)
        except ValidationError as e:
            self._logger.error(e)
            return 400, OrderErrorResponse(
                error_code=kuru_error_code_to_common(ErrorCode.INVALID_PARAMETER),
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

    async def _init_margin_account(self) -> MarginAccount:
        if self._margin_account is None:
            self._logger.info(f"Initializing margin account for contract {self._margin_contract_addr}")
            web3 = Web3(HTTPProvider(self._config["url"]))
            self._margin_account = MarginAccount(
                web3=web3, 
                contract_address=self._margin_contract_addr, 
                private_key=self._private_key
            )
            assert self._margin_account is not None
        
        return self._margin_account

    async def _get_wallet_balance(self, token_configs: Dict[str, dict]) -> Dict[str, Decimal]:
        """Get wallet balance for specified tokens"""
        web3 = Web3(HTTPProvider(self._config["url"]))
        account = web3.eth.account.from_key(self._private_key)
        wallet_address = account.address
        
        balances = {}
        
        for token_name, token_config in token_configs.items():
            token_address = token_config["address"]
            token_decimals = token_config["decimals"]
            
            if token_address.lower() == "0x0000000000000000000000000000000000000000":
                # Native token
                balance_wei = web3.eth.get_balance(wallet_address)
                balance = Decimal(str(from_wei(balance_wei, 'ether')))
                balances[token_name] = balance
            else:
                # ERC20 token
                try:
                    contract = web3.eth.contract(address=Web3.to_checksum_address(token_address), abi=self._erc20_abi)
                    balance_raw = contract.functions.balanceOf(wallet_address).call()
                    balance = Decimal(balance_raw) / Decimal(10 ** token_decimals)
                    balances[token_name] = balance
                except Exception as e:
                    self._logger.error(f"Failed to get balance for token {token_name} ({token_address}): {e}")
                    balances[token_name] = Decimal("0")
        
        return balances

    async def balance(self, path, params, received_at_ms) -> Tuple[int, Union[BalanceResponse, OrderErrorResponse]]:
        """Get wallet and margin account balances"""
        try:
            # Get wallet balances
            wallet_balances = await self._get_wallet_balance(self._common_tokens)
            
            # Get margin account balances 
            margin_balances = {}
            for token_name, token_config in self._common_tokens.items():
                token_address = token_config["address"]
                token_decimals = token_config["decimals"]
                
                balance_wei = await self._margin_account.get_balance(str(self._margin_account.wallet_address), token_address)
                
                # Convert balance using proper decimals
                if token_decimals == 18:
                    balance_decimal = Decimal(str(from_wei(balance_wei, 'ether')))
                else:
                    balance_decimal = Decimal(balance_wei) / Decimal(10 ** token_decimals)
                
                margin_balances[token_name] = balance_decimal
                self._logger.info(f"Margin account balance: {balance_decimal} for token {token_name}")
            
            # Convert to BalanceItem format
            wallet_balance_items = []
            exchange_wallet_balance_items = []
            
            for token_name in self._common_tokens.keys():
                token_config = self._common_tokens[token_name]
                symbol = token_config["symbol"]
                
                # Wallet balance
                wallet_balance = wallet_balances.get(token_name, Decimal("0"))
                wallet_balance_items.append(BalanceItem(symbol=symbol, balance=wallet_balance))
                
                # Exchange wallet balance (margin account)
                margin_balance = margin_balances.get(token_name, Decimal("0"))
                exchange_wallet_balance_items.append(BalanceItem(symbol=symbol, balance=margin_balance))
            
            return 200, BalanceResponse(
                balances={
                    "wallet": wallet_balance_items,
                    "exchange_wallet": exchange_wallet_balance_items
                }
            )
            
        except Exception as ex:
            self._logger.error(f"Failed to get balance: {ex}", exc_info=ex)
            return 400, OrderErrorResponse(
                error_code=kuru_error_code_to_common(ErrorCode.EXCHANGE_REJECTION),
                error_message=f"Failed to get balance: {str(ex)}"
            )


    async def deposit(self, path, params, received_at_ms) -> Tuple[int, Union[dict, OrderErrorResponse]]:
        """Deposit funds to margin account"""
        try:
            # Extract amount parameter
            amount = params.get('amount')
            if amount is None:
                return 400, OrderErrorResponse(
                    error_code=kuru_error_code_to_common(ErrorCode.INVALID_PARAMETER),
                    error_message="Missing required parameter 'amount'"
                )
            
            # Extract currency parameter (required)
            currency = params.get('currency')
            if currency is None:
                return 400, OrderErrorResponse(
                    error_code=kuru_error_code_to_common(ErrorCode.INVALID_PARAMETER),
                    error_message="Missing required parameter 'currency'"
                )
            
            token = currency.upper()
            if token not in self._common_tokens:
                return 400, OrderErrorResponse(
                    error_code=kuru_error_code_to_common(ErrorCode.INVALID_PARAMETER),
                    error_message=f"Unsupported currency '{currency}'. Supported currencies: {list(self._common_tokens.keys())}"
                )
            
            token_config = self._common_tokens[token]
            token_address = token_config["address"]
            token_decimals = token_config["decimals"]
            
            # Convert to float and validate
            try:
                amount_decimal = float(amount)
                if amount_decimal <= 0:
                    return 400, OrderErrorResponse(
                        error_code=kuru_error_code_to_common(ErrorCode.INVALID_PARAMETER),
                        error_message="Amount must be greater than 0"
                    )
            except (ValueError, TypeError):
                return 400, OrderErrorResponse(
                    error_code=kuru_error_code_to_common(ErrorCode.INVALID_PARAMETER),
                    error_message="Invalid amount format"
                )
            
            # Convert to token's native units (considering decimals)
            if token_decimals == 18:
                # Use ether for 18 decimal tokens
                size_wei = to_wei(amount_decimal, "ether")
            else:
                # For other decimals (like USDC with 6 decimals)
                size_wei = int(amount_decimal * (10 ** token_decimals))
            
            size_wei = 10 * math.ceil(float(size_wei) / 10)
            
            self._logger.info(f"Depositing to margin account: Contract: {self._margin_account.contract_address}, Amount: {amount_decimal} {currency}, Wei: {size_wei}")
            
            # Perform deposit
            margin_deposit_tx_hash = await self._margin_account.deposit(token_address, size_wei)
            self._logger.info(f"Deposit transaction hash: {margin_deposit_tx_hash}")
            
            assert margin_deposit_tx_hash is not None
            assert len(margin_deposit_tx_hash) > 0
            
            # Wait for confirmation
            web3 = Web3(HTTPProvider(self._config["url"]))
            tx_receipt = web3.eth.wait_for_transaction_receipt(HexStr(margin_deposit_tx_hash))
            assert tx_receipt["status"] == 1, "Deposit transaction failed"
            self._logger.info(f"Deposit transaction confirmed, block_number: {tx_receipt['blockNumber']}")
            
            return 200, {
                "tx_hash": margin_deposit_tx_hash,
                "amount": amount_decimal,
                "currency": token,
                "block_number": tx_receipt['blockNumber'],
                "status": "confirmed"
            }
            
        except Exception as ex:
            self._logger.error(f"Failed to deposit: {ex}", exc_info=ex)
            return 400, OrderErrorResponse(
                error_code=kuru_error_code_to_common(ErrorCode.EXCHANGE_REJECTION),
                error_message=f"Failed to deposit: {str(ex)}"
            )

    async def withdraw(self, path, params, received_at_ms) -> Tuple[int, Union[dict, OrderErrorResponse]]:
        """Withdraw funds from margin account to wallet"""
        try:
            # Extract currency parameter (required)
            currency = params.get('currency')
            if currency is None:
                return 400, OrderErrorResponse(
                    error_code=kuru_error_code_to_common(ErrorCode.INVALID_PARAMETER),
                    error_message="Missing required parameter 'currency'"
                )
            
            token = currency.upper()
            if token not in self._common_tokens:
                return 400, OrderErrorResponse(
                    error_code=kuru_error_code_to_common(ErrorCode.INVALID_PARAMETER),
                    error_message=f"Unsupported currency '{currency}'. Supported currencies: {list(self._common_tokens.keys())}"
                )
            
            token_config = self._common_tokens[token]
            token_address = token_config["address"]
            token_decimals = token_config["decimals"]
            
            # Get current balance
            balance = await self._margin_account.get_balance(str(self._margin_account.wallet_address), token_address)
            
            # Convert from token's native units to decimal format
            if token_decimals == 18:
                balance_decimal = from_wei(balance, 'ether')
            else:
                balance_decimal = balance / (10 ** token_decimals)
            
            self._logger.info(f"Withdrawing from margin account: {balance_decimal} {currency}")
            
            if balance > 0:
                # Perform withdrawal
                tx_hash = await self._margin_account.withdraw(token_address, balance)
                self._logger.info(f"Withdraw transaction hash: {tx_hash}")
                assert tx_hash is not None
                assert len(tx_hash) > 0
                
                # Wait for confirmation
                web3 = Web3(HTTPProvider(self._config["url"]))
                receipt = web3.eth.wait_for_transaction_receipt(HexStr(tx_hash))
                assert receipt["status"] == 1, f"Withdraw transaction failed {receipt}"
                
                # Verify balance is cleared
                new_balance = await self._margin_account.get_balance(str(self._margin_account.wallet_address), token_address)
                
                # Convert new balance using proper decimals
                if token_decimals == 18:
                    new_balance_decimal = from_wei(new_balance, 'ether')
                else:
                    new_balance_decimal = new_balance / (10 ** token_decimals)
                
                self._logger.info(f"New margin account balance: {new_balance_decimal} {currency}")
                assert new_balance == 0
                
                return 200, {
                    "tx_hash": tx_hash,
                    "withdrawn_amount": balance_decimal,
                    "currency": currency,
                    "block_number": receipt['blockNumber'],
                    "status": "withdrawn"
                }
            else:
                return 200, {
                    "message": f"Balance already zero for {currency}",
                    "currency": currency,
                    "status": "already_empty"
                }
                
        except Exception as ex:
            self._logger.error(f"Failed to withdraw: {ex}", exc_info=ex)
            return 400, OrderErrorResponse(
                error_code=kuru_error_code_to_common(ErrorCode.EXCHANGE_REJECTION),
                error_message=f"Failed to withdraw: {str(ex)}"
            )


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