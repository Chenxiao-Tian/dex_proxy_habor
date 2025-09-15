from typing import cast

import pytest
import pytest_asyncio

from dexes.kuru.handler.handler import KuruHandler, KuruHandlerSingleton
from dexes.kuru.handler.schemas import OrderSide, OrderType, OrderStatus, ErrorCode
from py_dex_common.schemas import OrderResponse


@pytest.fixture
def mock_config():
    return {
        "url": "http://localhost:8545",
    }

def make_CreateOrderResponse(overrides = None) -> OrderResponse:
    defaults = {
        "client_order_id": "0",
        "order_id": "",
        "price": "100.0",
        "quantity": "10.0",
        "total_exec_quantity": "0.0",
        "last_update_timestamp_ns": 1234567890000000000,
        "status": OrderStatus.OPEN,
        "trades": [],
        "order_type": OrderType.LIMIT,
        "symbol": "0xdefault_market",
        "side": OrderSide.BUY,
        "send_timestamp_ns": 1234567890000000000,
        "place_tx_id": "0xdefault_tx"
    }

    if overrides:
        defaults.update(overrides)

    return OrderResponse(**defaults)

class TestKuruHandlerSingleton:
    @pytest_asyncio.fixture(autouse=True)
    async def reset(self):
        await KuruHandlerSingleton.reset_instance()
        yield
        await KuruHandlerSingleton.reset_instance()

    def test_get_instance_creates_instance(self, mock_config):
        handler = KuruHandlerSingleton.get_instance(mock_config)
        assert isinstance(handler, KuruHandler)
        assert handler._config == mock_config

    def test_get_instance_returns_same_instance(self, mock_config):
        handler1 = KuruHandlerSingleton.get_instance(mock_config)
        handler2 = KuruHandlerSingleton.get_instance(mock_config)
        assert handler1 is handler2

    @pytest.mark.asyncio
    async def test_reset_instance_clears_instance(self, mock_config):
        KuruHandlerSingleton.get_instance(mock_config)
        assert KuruHandlerSingleton._instance is not None
        await KuruHandlerSingleton.reset_instance()
        assert KuruHandlerSingleton._instance is None

    @pytest.mark.asyncio
    async def test_reset_instance_with_specific_handler(self, mocker):
        mock_handler = mocker.MagicMock(spec=KuruHandler)
        await KuruHandlerSingleton.reset_instance(mock_handler)
        assert KuruHandlerSingleton._instance is mock_handler

        retrieved_handler = KuruHandlerSingleton.get_instance({}) # Passing a dummy config
        assert retrieved_handler is mock_handler


class TestKuruHandler:
    @pytest.fixture
    def handler(self, mock_config) -> KuruHandler:
        return KuruHandler(mock_config)

    def test_kuru_handler_init(self, handler, mock_config):
        assert handler._config == mock_config
        assert handler._private_key is None
        assert handler._logger is not None

    @pytest.mark.asyncio
    async def test_kuru_handler_start(self, handler, mocker):
        mocker.patch('dexes.kuru.handler.handler.KuruHandler._init_nonce_manager')

        test_private_key = "0xtestkey"
        await handler.start(test_private_key)
        assert handler._private_key == test_private_key

    @pytest.mark.asyncio
    async def test_create_web3(self, handler, mock_config, mocker):
        mock_cls_http_provider = mocker.patch('dexes.kuru.handler.handler.HTTPProvider')
        mock_cls_web3 = mocker.patch('dexes.kuru.handler.handler.Web3')
        
        mock_http_provider = mock_cls_http_provider.return_value
        mock_web3 = mock_cls_web3.return_value

        web3_instance = await handler._create_web3()

        mock_cls_http_provider.assert_called_once_with(
            endpoint_uri=mock_config["url"],
            # cacheable_requests={"eth_chainId"},
            # cache_allowed_requests=True
        )
        mock_cls_web3.assert_called_once_with(mock_http_provider)
        assert web3_instance is mock_web3

    @pytest.mark.asyncio
    async def test_create_client_order_executor(self, handler, mock_config, mocker):
        mock_cls_clientorderexecutor = mocker.patch('dexes.kuru.handler.handler.ClientOrderExecutor')
        
        mock_web3 = mocker.MagicMock()
        market_address = "0xmarketaddress"
        
        mock_client_executor = mock_cls_clientorderexecutor.return_value

        private_key = "0x123"
        handler._private_key = private_key
        client_executor = await handler._create_client_order_executor(market_address, mock_web3)

        mock_cls_clientorderexecutor.assert_called_once_with(
            web3=mock_web3,
            contract_address=market_address,
            private_key=private_key
        )
        assert client_executor is mock_client_executor

    @pytest.mark.asyncio
    async def test_create_client_order_executor_caching(self, handler, mock_config, mocker):
        mock_cls_clientorderexecutor = mocker.patch('dexes.kuru.handler.handler.ClientOrderExecutor')
        
        mock_web3 = mocker.MagicMock()
        market_address1 = "0xmarket1"
        market_address2 = "0xmarket2"
        
        mock_client_executor1 = mocker.MagicMock()
        mock_client_executor2 = mocker.MagicMock()
        mock_cls_clientorderexecutor.side_effect = [mock_client_executor1, mock_client_executor2]

        private_key = "0x123"
        handler._private_key = private_key
        
        # First call should create and cache client for market1
        client1_first_call = await handler._create_client_order_executor(market_address1, mock_web3)
        assert client1_first_call is mock_client_executor1
        assert market_address1 in handler._clients
        assert handler._clients[market_address1] is mock_client_executor1
        
        # Second call with same market address should return cached client
        client1_second_call = await handler._create_client_order_executor(market_address1, mock_web3)
        assert client1_second_call is mock_client_executor1
        assert client1_second_call is client1_first_call
        
        # Call with different market address should create new client
        client2 = await handler._create_client_order_executor(market_address2, mock_web3)
        assert client2 is mock_client_executor2
        assert market_address2 in handler._clients
        assert handler._clients[market_address2] is mock_client_executor2
        
        # Verify ClientOrderExecutor was called twice (once for each market)
        assert mock_cls_clientorderexecutor.call_count == 2
        mock_cls_clientorderexecutor.assert_any_call(
            web3=mock_web3,
            contract_address=market_address1,
            private_key=private_key
        )
        mock_cls_clientorderexecutor.assert_any_call(
            web3=mock_web3,
            contract_address=market_address2,
            private_key=private_key
        )

    @pytest.mark.asyncio
    async def test_init_nonce_manager(self, handler, mock_config, mocker):
        # Mock the dependencies
        mocker.patch('dexes.kuru.handler.handler.AsyncWeb3')
        mocker.patch('dexes.kuru.handler.handler.AsyncHTTPProvider')
        mock_cls_account = mocker.patch('dexes.kuru.handler.handler.Account')
        mock_cls_web3_request_manager = mocker.patch('dexes.kuru.handler.handler.Web3RequestManager')

        # Set up mock instances
        mock_nonce_manager = mock_cls_web3_request_manager.ensure_instance.return_value
        mock_cls_web3_request_manager.clear_instance = mocker.AsyncMock()
        mock_cls_web3_request_manager.ensure_instance = mocker.AsyncMock(return_value=mock_nonce_manager)
        mock_nonce_manager.start = mocker.AsyncMock()

        # Set up the handler with a private key (but don't call start to avoid double initialization)
        test_private_key = "0x123456789abcdef"
        handler._private_key = test_private_key

        result = await handler._init_nonce_manager()

        mock_cls_account.from_key.assert_called_once_with(test_private_key)

        # Verify the result
        assert result is mock_nonce_manager
        assert handler.nonce_manager is mock_nonce_manager

    @pytest.mark.asyncio
    async def test_create_order_success(
        self,
        handler: KuruHandler, 
        mocker
    ):
        mock_client = mocker.MagicMock()
        mock_cloid = "abd28d_buy_0.123"
        mock_client.place_order = mocker.AsyncMock(return_value=mock_cloid)

        mock_func_create_client_executor = mocker.patch('dexes.kuru.handler.handler.KuruHandler._create_client_order_executor')
        mock_func_create_client_executor.return_value = mock_client

        # Mock _init_nonce_manager and nonce manager
        mock_nonce_manager = mocker.MagicMock()
        mock_nonce_manager.get_nonce = mocker.AsyncMock(return_value=12345)
        mock_func_init_nonce_manager = mocker.patch('dexes.kuru.handler.handler.KuruHandler._init_nonce_manager')
        mock_func_init_nonce_manager.return_value = mock_nonce_manager
        handler.nonce_manager = mock_nonce_manager

        # Mock TxOptions
        mock_tx_options_cls = mocker.patch('dexes.kuru.handler.handler.TxOptions')
        mock_tx_options = mock_tx_options_cls.return_value

        # Mock the new timestamp function
        mocked_timestamp = 1234567890000000000  # Example timestamp in ns
        mocker.patch('dexes.kuru.handler.handler.get_current_timestamp_ns', return_value=mocked_timestamp)

        mock_params_input = {
            "symbol": "0xmarket_success_test",
            "quantity": "100",
            "price": "10",
            "side": OrderSide.BUY,
            "order_type": OrderType.LIMIT,
            "client_order_id": "123"
        }
        
        status, response = await handler.create_order("", mock_params_input, 12345)

        mock_client.place_order.assert_called_once_with(
            mocker.ANY, 
            async_execution=True, 
            callback=handler.on_create_order_transaction_completed, 
            callback_args=("123", "0xmarket_success_test"),
            tx_options=mock_tx_options
        )

        # Verify TxOptions was created with the correct nonce
        mock_tx_options_cls.assert_called_once_with(nonce=12345)
        mock_nonce_manager.get_nonce.assert_called_once()

        assert status == 200
        assert response.client_order_id == mock_params_input["client_order_id"]
        assert response.order_id == ""
        assert response.price == mock_params_input["price"]
        assert response.quantity == mock_params_input["quantity"]
        assert response.total_exec_quantity == "0"
        assert response.status == OrderStatus.OPEN
        assert response.trades == []
        assert response.order_type == mock_params_input["order_type"]
        assert response.symbol == mock_params_input["symbol"]
        assert response.side == mock_params_input["side"]
        assert response.send_timestamp_ns == mocked_timestamp
        assert response.place_tx_id == mock_cloid.split("_")[0]
        
        # Verify the order was saved to cache
        assert "123" in handler._orders_cache
        assert handler._orders_cache["123"] == response

    @pytest.mark.asyncio
    async def test_create_order_different_markets_use_different_clients(
        self,
        handler: KuruHandler, 
        mocker
    ):
        # Mock two different clients for two different markets
        mock_client1 = mocker.MagicMock()
        mock_client2 = mocker.MagicMock()
        mock_cloid1 = "abc123_buy_0.123"
        mock_cloid2 = "def456_buy_0.456"
        mock_client1.place_order = mocker.AsyncMock(return_value=mock_cloid1)
        mock_client2.place_order = mocker.AsyncMock(return_value=mock_cloid2)

        # Mock the client creation to return different clients for different markets
        mock_func_create_client_executor = mocker.patch('dexes.kuru.handler.handler.KuruHandler._create_client_order_executor')
        def side_effect(market_address, web3):
            if market_address == "0xmarket1":
                return mock_client1
            elif market_address == "0xmarket2":
                return mock_client2
            else:
                raise ValueError(f"Unexpected market address: {market_address}")
        mock_func_create_client_executor.side_effect = side_effect

        # Mock nonce manager
        mock_nonce_manager = mocker.MagicMock()
        mock_nonce_manager.get_nonce = mocker.AsyncMock(return_value=12345)
        handler.nonce_manager = mock_nonce_manager

        # Mock TxOptions
        mocker.patch('dexes.kuru.handler.handler.TxOptions')

        # Mock timestamp function
        mocked_timestamp = 1234567890000000000
        mocker.patch('dexes.kuru.handler.handler.get_current_timestamp_ns', return_value=mocked_timestamp)

        # Create order for first market
        mock_params_input1 = {
            "symbol": "0xmarket1",
            "quantity": "100",
            "price": "10",
            "side": OrderSide.BUY,
            "order_type": OrderType.LIMIT,
            "client_order_id": "123"
        }
        
        status1, response1 = await handler.create_order("", mock_params_input1, 12345)
        
        # Create order for second market
        mock_params_input2 = {
            "symbol": "0xmarket2",
            "quantity": "200",
            "price": "20",
            "side": OrderSide.BUY,
            "order_type": OrderType.LIMIT,
            "client_order_id": "456"
        }
        
        status2, response2 = await handler.create_order("", mock_params_input2, 12345)

        # Verify both orders were successful
        assert status1 == 200
        assert status2 == 200
        
        # Verify different clients were used
        mock_client1.place_order.assert_called_once()
        mock_client2.place_order.assert_called_once()
        
        # Verify client creation was called for both markets
        assert mock_func_create_client_executor.call_count == 2
        mock_func_create_client_executor.assert_any_call("0xmarket1", mocker.ANY)
        mock_func_create_client_executor.assert_any_call("0xmarket2", mocker.ANY)
        
        # Verify different place_tx_ids in responses
        assert response1.place_tx_id == mock_cloid1.split("_")[0]
        assert response2.place_tx_id == mock_cloid2.split("_")[0]
        assert response1.place_tx_id != response2.place_tx_id

    @pytest.mark.asyncio
    async def test_clear_clears_client_cache(self, handler, mocker):
        # Add some mock clients to the cache
        mock_client1 = mocker.AsyncMock()
        mock_client2 = mocker.AsyncMock()
        handler._clients["0xmarket1"] = mock_client1
        handler._clients["0xmarket2"] = mock_client2
        
        # Add some orders and completions to verify they're also cleared
        handler._orders_cache["order1"] = mocker.MagicMock()
        handler._order_completions["order1"] = mocker.MagicMock()
        handler._client_to_order_id_map["order1"] = 123
        
        # Mock nonce manager
        mock_nonce_manager = mocker.MagicMock()
        mock_nonce_manager.stop = mocker.AsyncMock()
        handler.nonce_manager = mock_nonce_manager
        
        # Verify caches have data
        assert len(handler._clients) == 2
        assert len(handler._orders_cache) == 1
        assert len(handler._order_completions) == 1
        assert len(handler._client_to_order_id_map) == 1
        
        # Call clear
        await handler.clear()
        
        # Verify all caches are cleared
        assert len(handler._clients) == 0
        assert len(handler._orders_cache) == 0
        assert len(handler._order_completions) == 0
        assert len(handler._client_to_order_id_map) == 0
        
        # Verify nonce manager stop was called
        mock_nonce_manager.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_orders(self, handler):
        path = "/orders"
        params = {}
        received_at_ms = 1234567890
        status, response = await handler.orders(path, params, received_at_ms)
        assert status == 200
        
        assert len(response.orders) == 0

    @pytest.mark.asyncio
    async def test_orders_with_cached_orders(self, handler):
        # Add some orders to the cache with different statuses
        order1 = OrderResponse(**{
            "client_order_id": "123",
            "order_id": "",
            "price": "100",
            "quantity": "10",
            "total_exec_quantity": "0",
            "last_update_timestamp_ns": 1234567890,
            "status": OrderStatus.OPEN,
            "trades": [],
            "order_type": "LIMIT",
            "symbol": "0xmarket1",
            "side": "BUY",
            "send_timestamp_ns": 1234567890,
            "place_tx_id": "0xtx1"
        })
        order2 = OrderResponse(**{
            "client_order_id": "124",
            "order_id": "",
            "price": "200",
            "quantity": "20",
            "total_exec_quantity": "0",
            "last_update_timestamp_ns": 1234567891,
            "status": OrderStatus.OPEN,
            "trades": [],
            "order_type": "LIMIT",
            "symbol": "0xmarket2",
            "side": "SELL",
            "send_timestamp_ns": 1234567891,
            "place_tx_id": "0xtx2"
        })
        # Must NOT be returned
        order3_cancelled = OrderResponse(**{
            "client_order_id": "125",
            "order_id": "",
            "price": "300",
            "quantity": "30",
            "total_exec_quantity": "0",
            "last_update_timestamp_ns": 1234567892,
            "status": "CANCELLED",
            "trades": [],
            "order_type": "LIMIT",
            "symbol": "0xmarket3",
            "side": "BUY",
            "send_timestamp_ns": 1234567892,
            "place_tx_id": "0xtx3"
        })
        # Must NOT be returned
        order4_rejected = OrderResponse(**{
            "client_order_id": "126",
            "order_id": "",
            "price": "400",
            "quantity": "40",
            "total_exec_quantity": "0",
            "last_update_timestamp_ns": 1234567893,
            "status": "REJECTED",
            "trades": [],
            "order_type": "LIMIT",
            "symbol": "0xmarket4",
            "side": "SELL",
            "send_timestamp_ns": 1234567893,
            "place_tx_id": "0xtx4"
        })
        handler._orders_cache["123"] = order1
        handler._orders_cache["124"] = order2
        handler._orders_cache["125"] = order3_cancelled
        handler._orders_cache["126"] = order4_rejected
        
        path = "/orders"
        params = {}
        received_at_ms = 1234567890
        status, response = await handler.orders(path, params, received_at_ms)
        assert status == 200

        # Should only return the 2 OPEN orders, not the CANCELLED or REJECTED ones
        assert len(response.orders) == 2
        assert order1 in response.orders
        assert order2 in response.orders

        # Verify all returned orders have OPEN status
        for order in response.orders:
            assert order.status == "OPEN"

    @pytest.mark.asyncio
    async def test_order_not_found(self, handler):
        params = {"client_order_id": "123"}
        status, response = await handler.order("", params, 12345)
        assert status == 404
        assert response["error_code"] == ErrorCode.ORDER_NOT_FOUND
        assert "not found" in response["error_message"]

    @pytest.mark.asyncio
    async def test_order_found(self, handler):
        # Add an order to the cache
        client_order_id = "123"
        order = OrderResponse(**{
            "client_order_id": client_order_id,
            "order_id": "",
            "price": "100",
            "quantity": "10",
            "total_exec_quantity": "0",
            "last_update_timestamp_ns": 1234567890,
            "status": OrderStatus.OPEN,
            "trades": [],
            "order_type": "LIMIT",
            "symbol": "0xmarket1",
            "side": "BUY",
            "send_timestamp_ns": 1234567890,
            "place_tx_id": "0xtx1",
        })
        handler._orders_cache[client_order_id] = order
        
        params = {"client_order_id": client_order_id}
        status, response = await handler.order("", params, 12345)
        assert status == 200
        assert response == order

    @pytest.mark.parametrize("params,expected_error", [
        pytest.param(
            {},
            "client_order_id is required",
            id="missing_client_order_id"
        ),
        pytest.param(
            {"client_order_id": "-1"},
            "must be a positive integer",
            id="negative_client_order_id"
        ),
        pytest.param(
            {"client_order_id": "0"},
            "must be a positive integer",
            id="zero_client_order_id"
        ),
        pytest.param(
            {"client_order_id": "abc"},
            "must be a valid integer",
            id="non_numeric_client_order_id"
        ),
    ])
    @pytest.mark.asyncio
    async def test_order_invalid_params(self, handler, params, expected_error):
        """Test order retrieval with various invalid parameters"""
        status, response = await handler.order("", params, 12345)
        assert status == 400
        assert response["error_code"] == "INVALID_PARAMETER"
        assert expected_error in response["error_message"]

    @pytest.mark.asyncio
    async def test_cancel_order_success(self, handler, mocker):
        """Test successful order cancellation"""
        # Setup existing order in cache
        client_order_id = "123"
        order_id = 456
        market_address = "0xmarket1"
        
        # order = make_CreateOrderResponse({
        #     "client_order_id": client_order_id
        # })
        order = OrderResponse(**{
            "client_order_id": client_order_id,
            "order_id": str(order_id),
            "price": "100",
            "quantity": "10",
            "total_exec_quantity": "0",
            "last_update_timestamp_ns": 1234567890,
            "status": OrderStatus.OPEN,
            "trades": [],
            "order_type": "LIMIT",
            "symbol": market_address,
            "side": "BUY",
            "send_timestamp_ns": 1234567890,
            "place_tx_id": "0xtx1"
        })
        handler._orders_cache[client_order_id] = order
        handler._client_to_order_id_map[client_order_id] = order_id
        
        # Mock dependencies
        mock_client = mocker.MagicMock()
        mock_client.cancel_orders = mocker.AsyncMock(return_value="0xcanceltx")
        
        mock_nonce_manager = mocker.MagicMock()
        mock_nonce_manager.get_nonce = mocker.AsyncMock(return_value=12345)
        handler.nonce_manager = mock_nonce_manager
        
        mocker.patch('dexes.kuru.handler.handler.KuruHandler._create_web3')
        mocker.patch('dexes.kuru.handler.handler.KuruHandler._create_client_order_executor', return_value=mock_client)
        mocker.patch('dexes.kuru.handler.handler.TxOptions')
        mocked_timestamp = 1234567891000000000
        mocker.patch('dexes.kuru.handler.handler.get_current_timestamp_ns', return_value=mocked_timestamp)
        
        # Test cancel order
        params = {"client_order_id": client_order_id}
        status, response = await handler.cancel_order("", params, 12345)
        
        # Verify response
        assert status == 200
        assert response.status == OrderStatus.CANCELLED_PENDING
        assert response.last_update_timestamp_ns == mocked_timestamp
        
        assert handler._orders_cache[client_order_id].status == OrderStatus.CANCELLED_PENDING
        assert handler._orders_cache[client_order_id].last_update_timestamp_ns == mocked_timestamp
        
        mock_client.cancel_orders.assert_called_once_with(
            market_address=market_address,
            order_ids=[order_id],
            tx_options=mocker.ANY
        )

    @pytest.mark.parametrize("params,expected_error", [
        pytest.param(
            {},
            "client_order_id is required",
            id="missing_client_order_id"
        ),
        pytest.param(
            {"client_order_id": "0"},
            "must be a positive integer",
            id="zero_client_order_id"
        ),
        pytest.param(
            {"client_order_id": "-1"},
            "must be a positive integer",
            id="negative_client_order_id"
        ),
        pytest.param(
            {"client_order_id": "abc"},
            "must be a valid integer",
            id="invalid_client_order_id"
        ),
    ])
    @pytest.mark.asyncio
    async def test_cancel_order_invalid_params(self, handler, params, expected_error):
        """Test cancel order with various invalid parameters"""
        status, response = await handler.cancel_order("", params, 12345)
        assert status == 400
        assert response.error_code == ErrorCode.INVALID_PARAMETER
        assert expected_error in response.error_message

    @pytest.mark.asyncio
    async def test_cancel_order_not_found(self, handler):
        """Test cancel order when order doesn't exist"""
        params = {"client_order_id": "999"}
        status, response = await handler.cancel_order("", params, 12345)
        assert status == 404
        assert response.error_code == ErrorCode.ORDER_NOT_FOUND
        assert "not found" in response.error_message

    @pytest.mark.asyncio
    async def test_cancel_order_not_open(self, handler):
        """Test cancel order when order is not in OPEN status"""
        client_order_id = "123"
        order = make_CreateOrderResponse({
            "client_order_id": client_order_id,
            "order_id": "456",
            "status": OrderStatus.CANCELLED,
            "symbol": "0xmarket1",
        })
        handler._orders_cache[client_order_id] = order
        
        params = {"client_order_id": client_order_id}
        status, response = await handler.cancel_order("", params, 12345)
        assert status == 404
        assert response.error_code == ErrorCode.ORDER_NOT_FOUND
        assert "not found" in response.error_message

    @pytest.mark.asyncio
    async def test_cancel_order_missing_order_id(self, handler):
        """Test cancel order when order_id mapping is missing"""
        client_order_id = "123"
        order = make_CreateOrderResponse({
            "client_order_id": client_order_id,
            "status": OrderStatus.OPEN,
            "symbol": "0xmarket1"
        })
        handler._orders_cache[client_order_id] = order
        # Note: not adding to _client_to_order_id_map
        
        params = {"client_order_id": client_order_id}
        status, response = await handler.cancel_order("", params, 12345)
        assert status == 404
        assert response.error_code == ErrorCode.ORDER_NOT_FOUND
        assert "Order ID not found" in response.error_message

    @pytest.mark.asyncio
    async def test_cancel_order_sdk_failure(self, handler, mocker):
        """Test cancel order when SDK cancel_orders fails"""
        # Setup
        client_order_id = "123"
        order_id = 456
        order = make_CreateOrderResponse({
            "client_order_id": client_order_id,
            "status": OrderStatus.OPEN,
            "symbol": "0xmarket1"
        })
        handler._orders_cache[client_order_id] = order
        handler._client_to_order_id_map[client_order_id] = order_id
        
        # Mock SDK to fail
        mock_client = mocker.MagicMock()
        mock_client.cancel_orders = mocker.AsyncMock(side_effect=Exception("SDK error"))
        
        mock_nonce_manager = mocker.MagicMock()
        mock_nonce_manager.get_nonce = mocker.AsyncMock(return_value=12345)
        handler.nonce_manager = mock_nonce_manager
        
        mocker.patch('dexes.kuru.handler.handler.KuruHandler._create_web3')
        mocker.patch('dexes.kuru.handler.handler.KuruHandler._create_client_order_executor', return_value=mock_client)
        mocker.patch('dexes.kuru.handler.handler.TxOptions')
        
        params = {"client_order_id": client_order_id}
        status, response = await handler.cancel_order("", params, 12345)
        
        assert status == 400
        assert response.error_code == ErrorCode.EXCHANGE_REJECTION
        assert "Failed to cancel order" in response.error_message

    @pytest.mark.parametrize("orders_setup,expected_count", [
        pytest.param(
            {},  # No orders
            0,
            id="no_orders"
        ),
        pytest.param(
            {
                "123": make_CreateOrderResponse({"client_order_id": "123", "status": OrderStatus.CANCELLED, "symbol": "0xmarket1"}),
                "124": make_CreateOrderResponse({"client_order_id": "124", "status": OrderStatus.REJECTED, "symbol": "0xmarket1"})
            },  # No OPEN orders
            0,
            id="no_open_orders"
        ),
    ])
    @pytest.mark.asyncio
    async def test_cancel_all_orders_empty_scenarios(self, handler: KuruHandler, orders_setup, expected_count):
        """Test cancel all orders when no cancellable orders exist"""
        # Setup orders cache
        for cid, order in orders_setup.items():
            handler._orders_cache[cid] = order
        
        status, response = await handler.cancel_all_orders("", {}, 12345)
        assert status == 200
        assert len(response.cancelled) == expected_count

    @pytest.mark.asyncio
    async def test_cancel_all_orders_single_market(self, handler: KuruHandler, mocker):
        """Test cancel all orders with orders from single market"""
        # Setup orders
        orders = {
            "123": make_CreateOrderResponse({
                "client_order_id": "123",
                "status": OrderStatus.OPEN,
                "symbol": "0xmarket1"
            }),
            "124": make_CreateOrderResponse({
                "client_order_id": "124",
                "status": OrderStatus.OPEN,
                "symbol": "0xmarket1"
            }),
        }
        for cid, order in orders.items():
            handler._orders_cache[cid] = order
            handler._client_to_order_id_map[cid] = int(cid) + 1000  # kuru order_id are 1123 and 1124
        
        # Mock dependencies
        mock_client = mocker.MagicMock()
        mock_client.cancel_orders = mocker.AsyncMock(return_value="0xcanceltx")
        
        mock_nonce_manager = mocker.MagicMock()
        mock_nonce_manager.get_nonce = mocker.AsyncMock(return_value=12345)
        handler.nonce_manager = mock_nonce_manager
        
        mocker.patch('dexes.kuru.handler.handler.KuruHandler._create_web3')
        mocker.patch('dexes.kuru.handler.handler.KuruHandler._create_client_order_executor', return_value=mock_client)
        mocker.patch('dexes.kuru.handler.handler.TxOptions')
        mocked_timestamp = 2000000000
        mocker.patch('dexes.kuru.handler.handler.get_current_timestamp_ns', return_value=mocked_timestamp)
        
        status, response = await handler.cancel_all_orders("", {}, 12345)
        
        assert status == 200
        assert len(response.cancelled) == 2
        
        # Verify all orders were cancelled
        for cancelled_order_id in response.cancelled:
            assert cancelled_order_id == 123 or cancelled_order_id == 124
        
        # Verify SDK was called with correct order_ids
        mock_client.cancel_orders.assert_called_once_with(
            market_address="0xmarket1",
            order_ids=[1123, 1124],  # order_ids for client_order_ids 123, 124
            tx_options=mocker.ANY
        )

    @pytest.mark.asyncio
    async def test_cancel_all_orders_multiple_markets(self, handler, mocker):
        """Test cancel all orders with orders from multiple markets"""
        # Setup orders across multiple markets
        orders = {
            "123": make_CreateOrderResponse({
                "client_order_id": "123",
                "status": OrderStatus.OPEN,
                "symbol": "0xmarket1",
                "last_update_timestamp_ns": 1000
            }),
            "124": make_CreateOrderResponse({
                "client_order_id": "124",
                "status": OrderStatus.OPEN,
                "symbol": "0xmarket2",
                "last_update_timestamp_ns": 1000
            }),
            "125": make_CreateOrderResponse({
                "client_order_id": "125",
                "status": OrderStatus.OPEN,
                "symbol": "0xmarket1",
                "last_update_timestamp_ns": 1000
            })
        }
        for cid, order in orders.items():
            handler._orders_cache[cid] = order
            handler._client_to_order_id_map[cid] = int(cid) + 1000
        
        # Mock different clients for different markets
        mock_client1 = mocker.MagicMock()
        mock_client1.cancel_orders = mocker.AsyncMock(return_value="0xcanceltx1")
        mock_client2 = mocker.MagicMock()
        mock_client2.cancel_orders = mocker.AsyncMock(return_value="0xcanceltx2")
        
        def client_side_effect(market_address, web3):
            if market_address == "0xmarket1":
                return mock_client1
            elif market_address == "0xmarket2":
                return mock_client2
            else:
                raise ValueError(f"Unexpected market: {market_address}")
        
        mock_nonce_manager = mocker.MagicMock()
        mock_nonce_manager.get_nonce = mocker.AsyncMock(return_value=12345)
        handler.nonce_manager = mock_nonce_manager
        
        mocker.patch('dexes.kuru.handler.handler.KuruHandler._create_web3')
        mocker.patch('dexes.kuru.handler.handler.KuruHandler._create_client_order_executor', side_effect=client_side_effect)
        mocker.patch('dexes.kuru.handler.handler.TxOptions')
        mocked_timestamp = 2000000000
        mocker.patch('dexes.kuru.handler.handler.get_current_timestamp_ns', return_value=mocked_timestamp)
        
        status, response = await handler.cancel_all_orders("", {}, 12345)
        
        assert status == 200
        assert len(response.cancelled) == 3

        # Verify both clients were called
        mock_client1.cancel_orders.assert_called_once_with(
            market_address="0xmarket1",
            order_ids=[1123, 1125],  # orders 123, 125
            tx_options=mocker.ANY
        )
        mock_client2.cancel_orders.assert_called_once_with(
            market_address="0xmarket2",
            order_ids=[1124],  # order 124
            tx_options=mocker.ANY
        )

    @pytest.mark.asyncio
    async def test_cancel_all_orders_partial_failure(self, handler, mocker):
        """Test cancel all orders when some markets fail"""
        # Setup orders across multiple markets
        orders = {
            "123": make_CreateOrderResponse({
                "client_order_id": "123",
                "status": OrderStatus.OPEN,
                "symbol": "0xmarket1",
                "last_update_timestamp_ns": 1000
            }),
            "124": make_CreateOrderResponse({
                "client_order_id": "124",
                "status": OrderStatus.OPEN,
                "symbol": "0xmarket2",
                "last_update_timestamp_ns": 1000
            })
        }
        for cid, order in orders.items():
            handler._orders_cache[cid] = order
            handler._client_to_order_id_map[cid] = int(cid) + 1000
        
        # Mock clients - one succeeds, one fails
        mock_client1 = mocker.MagicMock()
        mock_client1.cancel_orders = mocker.AsyncMock(return_value="0xcanceltx1")
        mock_client2 = mocker.MagicMock()
        mock_client2.cancel_orders = mocker.AsyncMock(side_effect=Exception("Market 2 failed"))
        
        def client_side_effect(market_address, web3):
            if market_address == "0xmarket1":
                return mock_client1
            elif market_address == "0xmarket2":
                return mock_client2
            else:
                raise ValueError(f"Unexpected market: {market_address}")
        
        mock_nonce_manager = mocker.MagicMock()
        mock_nonce_manager.get_nonce = mocker.AsyncMock(return_value=12345)
        handler.nonce_manager = mock_nonce_manager
        
        mocker.patch('dexes.kuru.handler.handler.KuruHandler._create_web3')
        mocker.patch('dexes.kuru.handler.handler.KuruHandler._create_client_order_executor', side_effect=client_side_effect)
        mocker.patch('dexes.kuru.handler.handler.TxOptions')
        mocked_timestamp = 2000000000
        mocker.patch('dexes.kuru.handler.handler.get_current_timestamp_ns', return_value=mocked_timestamp)
        
        status, response = await handler.cancel_all_orders("", {}, 12345)
        
        assert status == 400
        assert response.error_code == ErrorCode.EXCHANGE_REJECTION
        assert "Some orders failed to cancel" in response.error_message
        assert "Market 2 failed" in response.error_message
        
        assert len(response.cancelled) == 1
        assert response.cancelled[0] == 123

    # @pytest.mark.asyncio # <--- Added to async test method
    # async def test_create_order_place_order_fails_assertion(
    #     self,
    #     handler,
    #     mock_config,
    #     mocker
    # ):
    #     # Use mocker.patch
    #     mock_func_create_web3 = mocker.patch('dexes.kuru.handler.handler.KuruHandler._create_web3')
    #     mock_func_create_client_executor = mocker.patch('dexes.kuru.handler.handler.KuruHandler._create_client_order_executor')
        
    #     mock_params = {
    #         "symbol": "0xmarket_fail_test",
    #         "quantity": "200",
    #         "price": "20",
    #         "side": OrderSide.SELL,
    #         "order_type": OrderType.LIMIT,
    #         "client_order_id": "test_client_id_2"
    #         # Add other necessary params
    #     }

    #     # 1. Call actual CreateOrderIn.from_params
    #     order_input = CreateOrderIn.from_params(mock_params)

    #     # 2. Call actual validate_and_map_to_kuru_order_request
    #     kuru_order_request = validate_and_map_to_kuru_order_request(order_input)

    #     assert hasattr(kuru_order_request, 'market_address')
    #     assert kuru_order_request.market_address == mock_params["symbol"]

    #     mock_web3_instance = mocker.MagicMock()
    #     mock_func_create_web3.return_value = mock_web3_instance

    #     mock_client_executor_instance = mocker.MagicMock()
    #     mock_client_executor_instance.place_order = mocker.AsyncMock(return_value=None) 
    #     mock_func_create_client_executor.return_value = mock_client_executor_instance

    #     # No longer patching CreateOrderIn.from_params here
    #     with pytest.raises(AssertionError):
    #         await handler.create_order("/create_fail", mock_params, 67890) 