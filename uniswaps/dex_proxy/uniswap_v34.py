import json
import logging
from typing import Dict, Any

from pantheon.pantheon import Pantheon
from py_dex_common.dexes.dex_common import DexCommon
from pyutils.exchange_apis.dex_common import Request
from pyutils.exchange_apis.erc20web3_api import set_global_web3
from pyutils.exchange_apis.web3_client import Web3Client, Web3ClientConfig
from pyutils.exchange_connectors import ConnectorType
from pyutils.gas_pricing.eth import PriorityFee
from uniswap_shared.uniswap_v3 import UniswapV3
from uniswap_shared.uniswap_v4 import UniswapV4

from .routes import ServerRoutes


class UniswapV34(DexCommon):
    """
    The UniswapV34 class routes requests to either Uniswap V3 or V4 API endpoints
    based on explicit configuration parameters.
    
    This class uses composition to reuse the existing UniswapV3 and UniswapV4 classes
    rather than duplicating their logic. It delegates calls to the appropriate implementation
    based on explicit user preference - Users must specify 'v3' or 'v4' in the 'dex' parameter
    for each request to route it to the correct implementation
    
    Features:
    - Supports all operations from both V3 and V4 implementations
    - Routes method calls to appropriate V3/V4 instance based on 'dex' parameter
    - Special handling for wrap/unwrap token requests
    - Request status updates are properly forwarded to the correct instance
    
    Configuration:
    - A root config with common settings
    - Optional "v3" and "v4" sections with version-specific settings
    - Configuration is properly split between the two instances
    
    Request Handling:
    - Each request must specify a 'dex' parameter with value 'v3' or 'v4'
    - Status updates for requests are routed to the appropriate instance based on the 'dex' parameter
    """
    CHANNELS = ['ORDER']

    def __init__(self, pantheon: Pantheon, config: Dict[str, Any], server: Any, event_sink: Any):
        super().__init__(pantheon, config, server, event_sink)

        self._logger = logging.getLogger(config['name'])

        # Initialize both V3 and V4 instances for capital efficiency
        self._logger.info("Initializing both Uniswap V3 and V4 instances for capital efficiency")
        wallet = json.load(open(pantheon.config['key_store_file_path']))
        self.web3_client = Web3Client(Web3ClientConfig(
            wallet_address=wallet["address"],
            rpc_url=config["v3"]["connectors"]["uniswap_v3_arb_new"]["websocket"]["base_uri"],
        ))
        set_global_web3(self.web3_client)
        # Determine connector type for V3
        if config["v3"]["name"] == 'chainArb-uni3':
            connector_type_v3 = ConnectorType.UniswapV3ArbNew
        else:
            raise ValueError(f"Unsupported connector type for Uniswap V3: {config['v3']['name']}")
        # Initialize the V3 instance
        self._v3_instance = UniswapV3(pantheon, config["v3"], ServerRoutes(), event_sink, connector_type_v3)
        self._logger.info(f"Initialized Uniswap V3 instance with connector type: {connector_type_v3}")

        # Initialize the V4 instance
        self._v4_instance = UniswapV4(pantheon, config["v4"], ServerRoutes(), event_sink, ConnectorType.UniswapV4New)
        self._logger.info("Initialized Uniswap V4 instance")

        # Register endpoints
        self._server.register('POST', '/private/insert-order', self._insert_order)
        self._server.register("POST", "/private/wrap-unwrap-token", self._wrap_unwrap_token)

        # Get constants from V4 instance if available
        if hasattr(self._v4_instance, 'NATIVE_TOKEN_ADDRESS'):
            self.NATIVE_TOKEN_ADDRESS = self._v4_instance.NATIVE_TOKEN_ADDRESS
        if hasattr(self._v4_instance, 'NULL_HOOK_ADDRESS'):
            self.NULL_HOOK_ADDRESS = self._v4_instance.NULL_HOOK_ADDRESS

    async def start(self, private_key):
        """Start both V3 and V4 instances"""
        self._logger.info("Starting UniswapV34 service")
        await self.web3_client.init_account(private_key)

        # Start both V3 and V4 instances
        await self._v3_instance.start(private_key)
        await self._v4_instance.start(private_key)

        self._logger.info("UniswapV34 service started with both V3 and V4 support")

    def _select_dex(self, params: dict | Request) -> UniswapV3 | UniswapV4:
        """
        Select the appropriate Uniswap instance (V3 or V4) based on the 'dex' parameter.
        
        This is the core routing logic that determines which implementation handles a request.
        
        Args:
            params: Either a Request object or a dict containing request parameters
            
        Returns:
            The appropriate Uniswap instance (V3 or V4)
            
        Raises:
            ValueError: If the params type is invalid or no valid DEX version is specified
        """
        if isinstance(params, Request):
            dex = params.dex_specific['dex']
        elif isinstance(params, dict):
            dex = params['dex']
        else:
            raise ValueError("Invalid params type. Expected dict or Request.")

        if dex == 'v3':
            return self._v3_instance
        elif dex == 'v4':
            return self._v4_instance
        else:
            raise ValueError("No valid DEX version specified. Use 'v3' or 'v4' in params.")

    async def _insert_order(self, path, params: dict, received_at_ms):
        uniswap = self._select_dex(params)
        return await uniswap._insert_order(path, params, received_at_ms)

    async def _get_all_open_requests(self, path, params, received_at_ms):
        result = []
        result.extend(await self._v3_instance._get_all_open_requests(path, params, received_at_ms))
        result.extend(await self._v4_instance._get_all_open_requests(path, params, received_at_ms))
        return result

    async def on_new_connection(self, ws):
        return

    async def process_request(self, ws, request_id, method, params: dict):
        return False

    async def _approve(self, request, gas_price_wei, nonce=None):
        uniswap = self._select_dex(request)
        return await uniswap._approve(request, gas_price_wei, nonce)

    async def _transfer(self, request, gas_price_wei, nonce=None):
        uniswap = self._select_dex(request)
        return await uniswap._transfer(request, gas_price_wei, nonce)

    async def _amend_transaction(self, request: Request, params, gas_price_wei):
        uniswap = self._select_dex(request)
        return await uniswap._amend_transaction(request, params, gas_price_wei)

    async def _cancel_transaction(self, request: Request, gas_price_wei):
        uniswap = self._select_dex(request)
        return await uniswap._cancel_transaction(request, gas_price_wei)

    async def get_transaction_receipt(self, request, tx_hash):
        """Get transaction receipt from the appropriate Uniswap instance"""
        uniswap = self._select_dex(request)
        return await uniswap.get_transaction_receipt(request, tx_hash)

    def _get_gas_price(self, request, priority_fee: PriorityFee):
        """Get gas price from the appropriate Uniswap instance"""
        uniswap = self._select_dex(request)
        return uniswap._get_gas_price(request, priority_fee)

    async def on_request_status_update(self, client_request_id, request_status, tx_receipt: dict,
                                       mined_tx_hash: str = None):
        """
        Handle request status updates by routing them to the appropriate Uniswap instance (V3 or V4).
        This method determines which version handled the original request and forwards the status update.
        
        Args:
            client_request_id: The unique ID for the client request
            request_status: The current status of the request
            tx_receipt: Transaction receipt data from the blockchain
            mined_tx_hash: The hash of the mined transaction
        """
        # Get the request to determine which version was used
        request = self._request_cache.get(client_request_id)

        if not request:
            self._logger.warning(f"Received status update for unknown request ID: {client_request_id}")
            return

        # Determine which version to use based on the request's dex parameter
        if 'dex' in request.dex_specific:
            dex_version = request.dex_specific['dex']
            if dex_version == 'v3':
                await self._v3_instance.on_request_status_update(client_request_id, request_status, tx_receipt,
                                                                 mined_tx_hash)
            elif dex_version == 'v4':
                await self._v4_instance.on_request_status_update(client_request_id, request_status, tx_receipt,
                                                                 mined_tx_hash)
            else:
                self._logger.error(f"Unknown DEX version '{dex_version}' for request {client_request_id}")
        else:
            self._logger.error(f"No DEX version specified in request {client_request_id}")

    async def _cancel_all(self, path, params, received_at_ms):
        uniswap = self._select_dex(params)
        return await uniswap._cancel_all(path, params, received_at_ms)

    async def _wrap_unwrap_token(self, path, params: dict, received_at_ms):
        """Handle wrap/unwrap token requests"""
        uniswap = self._select_dex(params)
        return await uniswap._wrap_unwrap_token(path, params, received_at_ms)
