import logging
import random
from decimal import Decimal
from typing import Optional, Callable

from common.types import Ccy
from gateways.dex_proxy.dex_proxy_api_test_helper import DexProxyApiTestHelper
from gateways.dex_proxy.misc import http_client
from gateways.gateway import Gateway, Side
from gateways.models import OrderInsertResponse
#TODO: Dependency on GTE
from gte_py.models import OrderType


log = logging.getLogger(__name__)

class DexProxyGateway(Gateway):
    def __init__(
        self,
        config: dict,
    ):
        super().__init__(config)
        self.config = config
        self.next_client_order_id = 456000

    async def start(self, callback = None):
        client = http_client(self.config)
        self.api_helper = DexProxyApiTestHelper(client)
        await super().start(callback)


    async def stop(self):
        pass

    async def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        cancel_response = await self.api_helper.cancel_all_orders()
        if not cancel_response:
            return 0
        cancel_json = await cancel_response.json()
        return len(cancel_json.get("cancelled", []))

    async def place_order(
        self,
        instrument: str,
        side: Side,
        order_type: OrderType,
        price: Decimal,
        quantity: Decimal,
        client_order_id: Optional[str] = None,
        callback: Optional[Callable] = None,
    ) -> OrderInsertResponse:
        if client_order_id is None:
            client_order_id = self._generate_client_order_id()

        # Register callback if provided
        if callback:
            self.register_order_callback(client_order_id, callback)
        if instrument == "FX-SOL/USDC":
            instrument = "SOL"

        data = {
            "price": str(price.quantize(Decimal('0.000001'))),
            "quantity": str(quantity.quantize(Decimal('0.000001'))),
            "client_order_id": client_order_id,
            "side": "BUY" if side == Side.BUY else "SELL",
            "order_type": "GTC",
            "symbol": instrument,
        }

        order_response = await self.api_helper.make_order(data)
        order_json = await order_response.json()

        # TODO: Q: order_id and exec_qty will be empty here
        return OrderInsertResponse(
            order_id=order_json["place_tx_sig"],
            client_order_id=client_order_id,
            exec_qty=Decimal(0),
            rem_qty=quantity,
        )

    async def cancel_order(self, instrument: str, order_id: int, exchange_order_id: str) -> bool:
        data = {
            'client_order_id': order_id,
        }

        try:
            await self.api_helper.cancel_order(data)
        except Exception:
            log.exception("Exception while cancelling order")
            return False

        return True


    async def get_order_status(
        self, instrument: str, order_id: int, exchange_order_id: int
    ) -> Optional[dict]:
        try:
            order_response = await self.api_helper.get_order(order_id)
            order_json = await order_response.json()
            return {
                "exchange_order_id": order_json["order_id"],
                "status": order_json["status"],
                "qty": order_json["quantity"],
            }
        except Exception:
            log.exception("Exception while getting order status")
            return None

    async def get_available_balance(self, ccy: Ccy) -> Decimal:
        balance = await self.api_helper.get_balance()
        balance_json = await balance.json()
        for balance_data in balance_json.get('balances', []):
            if balance_data.get('symbol') == ccy.value:
                return Decimal(balance_data['balance']) / (Decimal(10) ** balance_data['decimals'])
        return Decimal('0')

    def _generate_client_order_id(self, prefix: str = "") -> str:
        self.next_client_order_id += 1

        return f"{self.next_client_order_id}"
