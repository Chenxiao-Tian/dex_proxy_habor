import asyncio
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from eth_account import Account
from eth_account.signers.local import LocalAccount
from eth_typing import ChecksumAddress
from gte_py.api.chain.utils import make_web3
from gte_py.api.chain.events import OrderCanceledEvent
from gte_py.clients import GTEClient
from gte_py.configs import TESTNET_CONFIG
from gte_py.models import Market, OrderSide as GteOrderSide, TimeInForce, MarketSide
from gte_py.models import OrderType
from web3 import AsyncWeb3

from common.types import Ccy
from common.utils import get_base_and_quote
from gateways.gateway import Gateway
from gateways.models import OrderInsertResponse
from ..gateway import Side


@dataclass
class GatewayOrder:
    exchange_order_id: str
    side: Side
    price: Decimal
    qty: Decimal
    status: str


def to_gte_order_side(side: Side) -> GteOrderSide:
    if side == Side.BID or side == Side.BUY:
        return GteOrderSide.BUY
    elif side == Side.ASK or side == Side.SELL:
        return GteOrderSide.SELL
    else:
        raise ValueError("unknown side")


def from_gte_order_side(side: GteOrderSide) -> Side:
    if side == GteOrderSide.BUY:
        return Side.BUY
    elif side == GteOrderSide.SELL:
        return Side.SELL
    else:
        raise ValueError("unknown order side")


def from_gte_market_side(side: MarketSide) -> Side:
    if side == MarketSide.BID:
        return Side.BUY
    elif side == MarketSide.ASK:
        return Side.SELL
    else:
        raise ValueError("unknown order side")


def from_gte_side(side: GteOrderSide | MarketSide) -> Side:
    if isinstance(side, GteOrderSide):
        return from_gte_order_side(side)
    elif isinstance(side, MarketSide):
        return from_gte_market_side(side)
    else:
        raise ValueError("unknown side type")


class GteDexGateway(Gateway):
    """Gateway for interacting with our Auros generic dex protocol"""

    def __init__(self, config: dict):
        super().__init__(config)
        self._address = AsyncWeb3.to_checksum_address(
            config["balance_provider"]["account"]
        )
        self._account: LocalAccount = Account.from_key(
            "719813462f4ce95de4d2354f3d5e31474f211b22c459ea8e808a87535263b74e"
        )
        self._w3 = None

        self._markets: dict[str, Market] = {}

        self.next_client_order_id = int(time.time() * 1000)
        self._balances = {}

        self._assets = {
            Ccy.ETH: AsyncWeb3.to_checksum_address(
                "0x776401b9bc8aae31a685731b7147d4445fd9fb19"
            ),
            Ccy.CUSD: AsyncWeb3.to_checksum_address(
                "0xE9b6e75C243B6100ffcb1c66e8f78F96FeeA727F"
            ),
        }
        self._client = GTEClient(
            config=TESTNET_CONFIG,
            wallet_private_key=self._account._private_key,
        )

    async def start(self, callback=None):
        await super().start(callback)

        await self._client.connect()

        await self.get_markets()
        await self.get_market(
            AsyncWeb3.to_checksum_address("0x5ca9f32d4ce7cc0f782213c446c2ae14b754a623")
        )
        await self._fetch_balance()
        # await self.get_market(
        #    AsyncWeb3.to_checksum_address("0xfaf0BB6F2f4690CA4319e489F6Dc742167B9fB10")
        # )

        await self.cancel_all_orders()

        asyncio.create_task(self._poll_orders())
        asyncio.create_task(self._poll_balances())

    async def stop(self):
        # any cleanup work
        pass

    async def cancel_all_orders(self, symbol: Optional[str] = None) -> int:
        """Cancel all open orders."""
        count = 0
        for market in self._markets.values():
            try:
                self.logger.info(f"Getting all orders for market {market.address}")
                orders = await self._client.info.get_open_orders(
                    market=market, address=self._account.address
                )
                self.logger.info(
                    f"Gotten {len(orders)} orders for market {market.address}"
                )
                for order in orders:
                    if order.status.value == "open":
                        await self._cancel_order(
                            market=market,
                            exchange_order_id=order.order_id,
                        )
                        count += 1
            except Exception as e:
                self.logger.error(f"Error canceling orders: {e}")
        return count

    async def _poll_orders(self):
        while True:
            # Get open orders
            # TODO

            await asyncio.sleep(1)

    async def get_markets(self):
        """Get market information."""
        try:
            print("Looking for on-chain CLOB markets...")
            markets = await self._client.info.get_markets(market_type="clob")
            for market in markets:
                self._markets[market.address] = market
        except Exception as e:
            self.logger.error(f"Error getting on-chain markets: {e}", exc_info=True)

    async def get_market(self, address: ChecksumAddress):
        """Get market information by address."""
        try:
            self.logger.info(f"Getting market info for {address}")
            market = await self._client.info.get_market(address)
            self.logger.info(f"Market {address} info: {market}")
            self._markets[address] = market
        except Exception as e:
            self.logger.error(f"Error getting market by address: {e}", exc_info=True)

    def _generate_client_order_id(self) -> str:
        """Generate a unique client order ID specifically for GTE"""
        self.next_client_order_id += 1
        return f"{self.address[:8]}-{self.next_client_order_id}"

    def _get_market_from_instrument(self, instrument: str):
        base, quote = get_base_and_quote(instrument)
        for market in self._markets.values():
            if market.base.symbol == base.value and market.quote.symbol == quote.value:
                return market

        raise ValueError(f"No market found for {instrument}")

    async def place_order(
            self,
            instrument: str,
            side: Side,
            order_type: OrderType,
            price: Decimal,
            quantity: Decimal,
            client_order_id: str = None,
            callback=None,
    ) -> OrderInsertResponse:
        if client_order_id is None:
            client_order_id = self._generate_client_order_id()

        # Register callback if provided
        if callback:
            self.register_order_callback(client_order_id, callback)

        market = self._get_market_from_instrument(instrument)


        order = await self._client.execution.place_limit_order(
            market=market,
            side=to_gte_order_side(side),
            amount=quantity,
            price=price,
            time_in_force=TimeInForce.GTC,
            client_order_id=int(client_order_id),
            gas=50 * 10000000,
        )
        if not order:
            self.logger.error(f"Order {client_order_id} failed to place, none returned")
            return None

        self.logger.info(f"Order {client_order_id} placed: {order}")

        return OrderInsertResponse(
            order_id=str(order['id']),
            client_order_id=client_order_id,
            side=from_gte_side(order['side']),
            price=Decimal(order['price']) / 10 ** market.quote.decimals,
            rem_qty=Decimal(order['amount']) / 10 ** market.base.decimals,
            exec_qty=quantity - Decimal(order['amount']) / 10 ** market.base.decimals,
            status=order['status'],
        )

    async def cancel_order(
            self, instrument: str, order_id: int, exchange_order_id: str
    ) -> bool:
        market = self._get_market_from_instrument(instrument)
        await self._cancel_order(market, exchange_order_id)
        self.logger.info(f"Cancelled order {order_id}")
        return True

    async def _cancel_order(self, market: Market, exchange_order_id: str):
        resp: OrderCanceledEvent = await self._client.execution.cancel_order(
            market=market,
            order_id=int(exchange_order_id),
            gas=200000,
        )

        self.logger.info(f"Cancelling order processed: {resp}")
        return resp

    async def get_order_status(
            self, instrument: str, order_id: int, exchange_order_id: int
    ) -> Optional[dict]:
        self.logger.info(
            f"Getting order status for {order_id}, exchange order id {exchange_order_id}"
        )
        market = self._get_market_from_instrument(instrument)

        order = await self._client.info.get_order(
            market=market,
            order_id=exchange_order_id,
        )
        if order:
            self.logger.info(f"Order {order_id} status: {order}")
            return {
                "exchange_order_id": order.order_id,
                "status": order.status.value,
                "qty": order.amount,
            }
        return None

    async def _fetch_balance(self):
        for ccy, address in self._assets.items():
            try:
                _, balance = await self._client.execution.get_balance(
                    address, self._address
                )
                self.logger.info(f"{ccy.value} exchange balance: {balance}")
                self._balances[ccy] = Decimal(balance)
            except Exception as e:
                self.logger.error(
                    f"Error getting balance for {ccy.value}: {e}", exc_info=True
                )

    async def _poll_balances(self):
        while True:
            await self._fetch_balance()
            await asyncio.sleep(2)

    async def get_available_balance(self, ccy: Ccy) -> Decimal:
        return self._balances.get(ccy, Decimal(0))
