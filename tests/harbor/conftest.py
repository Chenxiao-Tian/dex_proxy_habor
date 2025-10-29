import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import types

if 'pantheon' not in sys.modules:
    pantheon_stub = types.ModuleType('pantheon')

    class _DummyPantheon:
        def __init__(self, *args, **kwargs):
            self.config = {}
            self.loop = None
            self.process_name = 'harbor-test'

    class _DummyArgParser:
        def __init__(self, *args, **kwargs):
            pass

    pantheon_stub.Pantheon = _DummyPantheon
    pantheon_stub.StandardArgParser = _DummyArgParser
    sys.modules['pantheon'] = pantheon_stub

if 'web3' not in sys.modules:
    web3_stub = types.ModuleType('web3')

    class _Web3:
        @staticmethod
        def to_checksum_address(address):
            return address

    exceptions_module = types.ModuleType('web3.exceptions')

    class _TransactionNotFound(Exception):
        pass

    exceptions_module.TransactionNotFound = _TransactionNotFound
    web3_stub.Web3 = _Web3
    web3_stub.exceptions = exceptions_module
    sys.modules['web3'] = web3_stub
    sys.modules['web3.exceptions'] = exceptions_module

if 'pyutils' not in sys.modules:
    pyutils_stub = types.ModuleType('pyutils')
    exchange_apis = types.ModuleType('pyutils.exchange_apis')
    dex_common = types.ModuleType('pyutils.exchange_apis.dex_common')

    class _RequestStatus:
        SUCCEEDED = 'SUCCEEDED'
        FAILED = 'FAILED'
        CANCELED = 'CANCELED'

    class _RequestType:
        class _Item:
            def __init__(self, name):
                self.name = name

        ORDER = _Item('ORDER')
        TRANSFER = _Item('TRANSFER')
        APPROVE = _Item('APPROVE')
        WRAP_UNWRAP = _Item('WRAP_UNWRAP')

        def __getitem__(self, item):
            return getattr(self, item)

    class _Request:
        def __init__(self):
            self.client_request_id = ''
            self.request_type = _RequestType.ORDER
            self.request_status = _RequestStatus.SUCCEEDED
            self.nonce = None
            self.tx_hashes = []
            self.used_gas_prices_wei = []
            self.dex_specific = {}

        def to_dict(self):
            return {}

        def is_finalised(self):
            return True

        def finalise_request(self, status):
            self.request_status = status

    class _OrderRequest(_Request):
        @classmethod
        def from_json(cls, data):
            return cls()

    class _TransferRequest(_Request):
        @classmethod
        def from_json(cls, data):
            return cls()

    class _ApproveRequest(_Request):
        @classmethod
        def from_json(cls, data):
            return cls()

    class _WrapUnwrapRequest(_Request):
        @classmethod
        def from_json(cls, data):
            return cls()

    exchange_apis.dex_common = dex_common
    dex_common.RequestStatus = _RequestStatus
    dex_common.RequestType = _RequestType()
    dex_common.Request = _Request
    dex_common.OrderRequest = _OrderRequest
    dex_common.TransferRequest = _TransferRequest
    dex_common.ApproveRequest = _ApproveRequest
    dex_common.WrapUnwrapRequest = _WrapUnwrapRequest

    pyutils_stub.exchange_apis = exchange_apis
    exchange_apis.__path__ = []
    sys.modules['pyutils'] = pyutils_stub
    sys.modules['pyutils.exchange_apis'] = exchange_apis
    sys.modules['pyutils.exchange_apis.dex_common'] = dex_common

    exchange_connectors = types.ModuleType('pyutils.exchange_connectors')

    class _ConnectorType:
        Native = object()

    exchange_connectors.ConnectorType = _ConnectorType
    exchange_connectors.__path__ = []
    sys.modules['pyutils.exchange_connectors'] = exchange_connectors

    gas_pricing = types.ModuleType('pyutils.gas_pricing')
    eth_module = types.ModuleType('pyutils.gas_pricing.eth')

    class _PriorityFee:
        Fast = object()

    eth_module.PriorityFee = _PriorityFee
    gas_pricing.eth = eth_module
    sys.modules['pyutils.gas_pricing'] = gas_pricing
    sys.modules['pyutils.gas_pricing.eth'] = eth_module

if 'utils.redis_batch_executor' not in sys.modules:
    utils_module = types.ModuleType('utils')
    redis_executor = types.ModuleType('utils.redis_batch_executor')

    class _RedisBatchExecutor:
        def __init__(self, *args, **kwargs):
            pass

        def execute(self, *args, **kwargs):
            return None

    redis_executor.RedisBatchExecutor = _RedisBatchExecutor
    sys.modules['utils'] = utils_module
    sys.modules['utils.redis_batch_executor'] = redis_executor

if 'pyutils.exchange_apis.fordefi_api' not in sys.modules:
    fordefi_module = types.ModuleType('pyutils.exchange_apis.fordefi_api')

    class _FordefiApi:
        async def start(self):
            pass

    fordefi_module.FordefiApi = _FordefiApi
    sys.modules['pyutils.exchange_apis.fordefi_api'] = fordefi_module

if 'pyutils.exchange_apis.fireblocks_api' not in sys.modules:
    fireblocks_module = types.ModuleType('pyutils.exchange_apis.fireblocks_api')

    class _FireblocksApi:
        async def start(self):
            pass

    fireblocks_module.FireblocksApi = _FireblocksApi
    sys.modules['pyutils.exchange_apis.fireblocks_api'] = fireblocks_module
if 'pyutils.exchange_connectors.fordefi_connector' not in sys.modules:
    fordefi_connector = types.ModuleType('pyutils.exchange_connectors.fordefi_connector')

    class _FordefiConnector:
        pass

    class _FordefiConfiguration:
        pass

    fordefi_connector.FordefiConnector = _FordefiConnector
    fordefi_connector.FordefiConfiguration = _FordefiConfiguration
    sys.modules['pyutils.exchange_connectors.fordefi_connector'] = fordefi_connector

if 'pyutils.exchange_connectors.fireblocks_connector' not in sys.modules:
    fireblocks_connector = types.ModuleType('pyutils.exchange_connectors.fireblocks_connector')

    class _FireblocksConnector:
        pass

    class _FireblocksConfiguration:
        pass

    fireblocks_connector.FireblocksConnector = _FireblocksConnector
    fireblocks_connector.FireblocksConfiguration = _FireblocksConfiguration
    sys.modules['pyutils.exchange_connectors.fireblocks_connector'] = fireblocks_connector


if 'py_dex_common' not in sys.modules:
    py_dex_common = types.ModuleType('py_dex_common')
    schemas_module = types.ModuleType('py_dex_common.schemas')

    class _BaseModel:
        def model_dump(self):
            return self.__dict__

    class BalanceItem(_BaseModel):
        def __init__(self, symbol, balance):
            self.symbol = symbol
            self.balance = balance

    class BalanceResponse(_BaseModel):
        def __init__(self, balances):
            self.balances = balances

    class CancelOrderParams(_BaseModel):
        def __init__(self, client_order_id):
            self.client_order_id = client_order_id

    class CreateOrderRequest(_BaseModel):
        def __init__(self, client_order_id, symbol, price, quantity, side, order_type):
            self.client_order_id = client_order_id
            self.symbol = symbol
            self.price = price
            self.quantity = quantity
            self.side = side
            self.order_type = order_type

    class OrderErrorResponse(_BaseModel):
        def __init__(self, error_code, error_message):
            self.error_code = error_code
            self.error_message = error_message

    class OrderResponse(_BaseModel):
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class QueryLiveOrdersResponse(_BaseModel):
        def __init__(self, send_timestamp_ns, orders):
            self.send_timestamp_ns = send_timestamp_ns
            self.orders = orders

    schemas_module.BalanceItem = BalanceItem
    schemas_module.BalanceResponse = BalanceResponse
    schemas_module.CancelOrderParams = CancelOrderParams
    schemas_module.CreateOrderRequest = CreateOrderRequest
    schemas_module.OrderErrorResponse = OrderErrorResponse
    schemas_module.OrderResponse = OrderResponse
    schemas_module.QueryLiveOrdersResponse = QueryLiveOrdersResponse

    dexes_module = types.ModuleType('py_dex_common.dexes')
    dex_common_module = types.ModuleType('py_dex_common.dexes.dex_common')

    class DexCommon:
        CHANNELS = []

        def __init__(self, pantheon, config, server, event_sink):
            self.pantheon = pantheon
            self._config = config
            self._server = server
            self._event_sink = event_sink
            self.started = False

        async def start(self, private_key):
            self.started = True

        async def on_new_connection(self, ws):
            return None

        async def process_request(self, ws, request_id, method, params):
            return False

        async def _approve(self, request, gas_price_wei, nonce=None):
            raise NotImplementedError

        async def _transfer(self, request, gas_price_wei, nonce=None):
            raise NotImplementedError

        async def _amend_transaction(self, request, params, gas_price_wei):
            raise NotImplementedError

        async def _cancel_transaction(self, request, gas_price_wei):
            raise NotImplementedError

        async def get_transaction_receipt(self, request, tx_hash):
            return None

        def _get_gas_price(self, request, priority_fee):
            return None

        async def _get_all_open_requests(self, path, params, received_at_ms):
            return 200, []

        async def _cancel_all(self, path, params, received_at_ms):
            return 200, []

        def on_request_status_update(self, client_request_id, request_status, tx_receipt, mined_tx_hash=None):
            return None

        def get_request(self, client_request_id):
            return None

    dex_common_module.DexCommon = DexCommon


    web_server_module = types.ModuleType('py_dex_common.web_server')

    class WebServer:
        def __init__(self, *args, **kwargs):
            self.registered = []

        def register(self, *args, **kwargs):
            self.registered.append((args, kwargs))

        async def start(self):
            return None

        async def stop(self):
            return None

        async def send_json(self, ws, payload):
            return None

    web_server_module.WebServer = WebServer
    sys.modules['py_dex_common.web_server'] = web_server_module
    py_dex_common.schemas = schemas_module
    py_dex_common.dexes = dexes_module
    sys.modules['py_dex_common'] = py_dex_common
    sys.modules['py_dex_common.schemas'] = schemas_module
    sys.modules['py_dex_common.dexes'] = dexes_module
    sys.modules['py_dex_common.dexes.dex_common'] = dex_common_module

if 'aiohttp' not in sys.modules:
    aiohttp_module = types.ModuleType('aiohttp')

    class ClientTimeout:
        def __init__(self, total=None):
            self.total = total

    class _DummyResponse:
        def __init__(self, status=200, payload='{}'):
            self.status = status
            self._payload = payload

        async def text(self):
            return self._payload

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class ClientSession:
        def __init__(self, *args, **kwargs):
            pass

        async def request(self, method, url, params=None, json=None, headers=None):
            return _DummyResponse()

        async def close(self):
            return None

    aiohttp_module.ClientSession = ClientSession
    aiohttp_module.ClientTimeout = ClientTimeout
    sys.modules['aiohttp'] = aiohttp_module
