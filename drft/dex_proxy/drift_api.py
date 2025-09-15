import aiohttp
import logging
from decimal import Decimal
from enum import auto
from typing import Dict, List, Optional, Literal, Any, AsyncGenerator
from datetime import datetime

from .drift_connector import DriftConnection

from pantheon.movements import Trade
from pantheon.pantheon_types import OrderType, Side, TradeLiquidity, EEID, OpenClose
from pantheon.timestamp_ns import TimestampNs
from pantheon.utils import SerialisableEnum

from driftpy.constants.numeric_constants import BASE_PRECISION, PRICE_PRECISION
from driftpy.decode.utils import decode_name
from driftpy.drift_client import DriftClient
from driftpy.math.conversion import convert_to_number
from driftpy.types import (
    Order as DriftOrder,
    OrderStatus as DriftOrderStatus,
    PositionDirection,
    is_variant,
    SpotMarketAccount,
    PerpMarketAccount,
)


logger = logging.getLogger("drift_api")
MarketType = Literal["spot", "perp"]


# https://github.com/drift-labs/driftpy/issues/220
def equal_drift_enum(a: Any, b: Any):
    return a.index == b.index


def equal_drift_enum_str(a: Any, b: Any):
    a_str = str(a).lower()
    b_str = str(b).lower()
    return a_str in b_str or b_str in a_str


def direction_to_side(direction: PositionDirection) -> Side:
    if equal_drift_enum(direction, PositionDirection.Long()):
        return Side.BUY
    elif equal_drift_enum(direction, PositionDirection.Short()):
        return Side.SELL
    else:
        raise Exception("Unknown direction: {}".format(direction))


def get_order_type(drift_order: DriftOrder) -> OrderType:
    if drift_order.post_only:
        return OrderType.GTC_POST_ONLY
    if drift_order.immediate_or_cancel:
        return OrderType.IOC
    return OrderType.GTC


def direction_to_side_str(direction: str) -> Side:
    if equal_drift_enum_str(direction, "Long"):
        return Side.BUY
    elif equal_drift_enum_str(direction, "Short"):
        return Side.SELL
    else:
        raise Exception("Unknown direction: {}".format(direction))


def convert_order_status(status: DriftOrderStatus) -> "OrderStatus":
    if equal_drift_enum(status, DriftOrderStatus.Init()):
        logger.warning("Order is in Init state, but we record it as OPEN")
        return OrderStatus.OPEN
    elif equal_drift_enum(status, DriftOrderStatus.Open()):
        return OrderStatus.OPEN
    elif equal_drift_enum(status, DriftOrderStatus.Canceled()):
        return OrderStatus.CANCELLED
    elif equal_drift_enum(status, DriftOrderStatus.Filled()):
        return OrderStatus.EXPIRED
    else:
        logger.warning("Unknown status, but we record it as EXPIRED: %s", status)
        return OrderStatus.EXPIRED


class DriftApi:
    def __init__(self, connection: DriftConnection):
        self.conn: DriftConnection = connection
        self.http_session = aiohttp.client.ClientSession()
        self.account_address = str(self.conn.client.get_user_account_public_key())

    def show_user_info(self):
        self.conn.show_user_info()

    def get_spot_market_accounts(self):
        return self.conn.client.get_spot_market_accounts()

    def get_perp_market_accounts(self):
        return self.conn.client.get_perp_market_accounts()

    async def force_get_markets(self, market):
        all_markets = await self.conn.client.program.account[market].all()
        all_markets = sorted(all_markets, key=lambda x: x.account.market_index)
        all_markets = {
            x.account.market_index: decode_name(x.account.name) for x in all_markets
        }
        return all_markets

    def get_spot_positions(self) -> Dict[str, float]:
        user = self.conn.client.get_user(self.conn.client.active_sub_account_id)
        user_account = user.get_user_account()
        positions = {}
        for position in user_account.spot_positions:
            if position.market_index == 0 and position.scaled_balance == 0:
                break
            spot = self.conn.client.get_spot_market_account(position.market_index)
            name = decode_name(spot.name)
            balance = convert_to_number(
                user.get_token_amount(spot.market_index), pow(10, spot.decimals)
            )
            positions[name] = balance
        return positions

    def get_perp_positions(self) -> Dict[str, float]:
        user = self.conn.client.get_user(self.conn.client.active_sub_account_id)
        user_account = user.get_user_account()
        positions = {}
        for position in user_account.perp_positions:
            if position.base_asset_amount == 0:
                break
            perp = self.conn.client.get_perp_market_account(position.market_index)
            name = decode_name(perp.name)
            position = convert_to_number(position.base_asset_amount, BASE_PRECISION)
            positions[name] = position
        return positions

    def convert_order(self, drift_order: DriftOrder) -> "Order":
        symbol = self._convert_to_auros_instrument(
            str(drift_order.market_type), drift_order.market_index
        )
        order = Order(
            received_at=TimestampNs.now(),
            auros_order_id=None,
            drift_user_order_id=drift_order.user_order_id,
            drift_order_id=drift_order.order_id,
            price=Decimal(drift_order.price),
            qty=Decimal(drift_order.base_asset_amount),
            side=direction_to_side(drift_order.direction),
            order_type=get_order_type(drift_order),
            symbol=symbol,
            slot=drift_order.slot,
            status=convert_order_status(drift_order.status),
        )
        order.fill_market(
            drift_order.market_index, str(drift_order.market_type), self.conn.client
        )

        order.price /= order.price_mult
        order.qty /= order.qty_mult
        order.total_executed_qty = (
            Decimal(drift_order.base_asset_amount_filled) / order.qty_mult
        )

        return order

    def get_open_orders(self) -> List["Order"]:
        user = self.conn.client.get_user()
        result = []
        for order in user.get_open_orders():
            result.append(self.convert_order(order))
        return result

    def get_recent_orders(self) -> List["Order"]:
        user = self.conn.client.get_user()
        result = []
        for order in user.get_user_account().orders:
            result.append(self.convert_order(order))
        return result

    async def get_accounts(
        self, market: Literal["SpotMarket", "PerpMarket"]
    ) -> Dict[int, str]:
        all_markets = await self.conn.client.program.account[market].all()
        all_markets = {
            x.account.market_index: bytes(x.account.name).decode("utf-8").strip()
            for x in all_markets
        }
        return all_markets

    def _convert_symbol(self, native_name: str) -> str:
        return native_name.replace("-PERP", "").upper()

    def _convert_to_auros_instrument(
        self, market_type: str | MarketType, market_index: int
    ) -> str | None:
        if equal_drift_enum_str(market_type, "Perp"):
            perp = self.conn.client.get_perp_market_account(market_index)
            base = self._convert_symbol(decode_name(perp.name))
            quote = "USDC"
            return f"PSWP-{base}/{quote}"
        elif equal_drift_enum_str(market_type, "Spot"):
            spot = self.conn.client.get_spot_market_account(market_index)
            base = self._convert_symbol(decode_name(spot.name))
            quote = "USDC"
            return f"FX-{base}/{quote}"
        else:
            raise Exception(f"Unknown market type {market_type}")

    def __lookup_drift_instrument(
        self, market_type: str | MarketType, market_index: int
    ) -> PerpMarketAccount | SpotMarketAccount | None:
        if is_variant(market_type, "Perp"):
            return self.conn.client.get_perp_market_account(market_index)
        elif is_variant(market_type, "Spot"):
            return self.conn.client.get_spot_market_account(market_index)
        elif isinstance(market_type, str):
            market_type = market_type.lower()
            if market_type == "perp":
                return self.conn.client.get_perp_market_account(market_index)
            elif market_type == "spot":
                return self.conn.client.get_spot_market_account(market_index)
            else:
                logger.error("Unknown market type variant %s", market_type)
        else:
            logger.error("Unknown market type %s %s", type(market_type), market_type)

    async def fetch_trades_raw(self, next_page: str | None = None) -> List[dict]:
        if not next_page:
            url = f"https://data.api.drift.trade/user/{str(self.conn.client.get_user_account_public_key())}/trades"
        # Remove None values from params
        else:
            url = f"https://data.api.drift.trade/user/{str(self.conn.client.get_user_account_public_key())}/trades?page={next_page}"

        resp = await self.http_session.get(url)
        resp.raise_for_status()
        result = await resp.json()

        return result

    async def fetch_trades(
        self, logger: logging.Logger, poll_start_time: datetime
    ) -> AsyncGenerator[List[Trade], None]:
        next_page = None
        has_more = True
        page_limit = 20
        while has_more:
            response = await self.fetch_trades_raw(next_page)
            trades_raw = response.get("records", [])
            next_page = response.get("meta", {}).get("nextPage")
            if not trades_raw:
                has_more = False
                break

            trades = []
            for trade in trades_raw:
                try:
                    logger.debug("[TRADE] %s", trade)
                    market = self.__lookup_drift_instrument(
                        trade["marketType"], trade["marketIndex"]
                    )
                    if not market:
                        logger.warning("Market not found for trade %s", trade)
                        continue

                    instrument = self._convert_to_auros_instrument(
                        trade["marketType"], trade["marketIndex"]
                    )

                    if trade.get("taker") == self.account_address:
                        order_id = trade["takerOrderId"]
                        fee = Decimal(trade["takerFee"])
                        liquidity = TradeLiquidity.TAKER
                        order_direction = trade["takerOrderDirection"]
                    elif trade.get("maker") == self.account_address:
                        order_id = trade["makerOrderId"]
                        fee = Decimal(trade["makerFee"])
                        liquidity = TradeLiquidity.MAKER
                        order_direction = trade["makerOrderDirection"]
                    else:
                        logger.error("Unknown TradeLiquidity: %s", trade)
                        continue

                    fill_record_id: str = trade["fillRecordId"]
                    quantity = Decimal(trade["baseAssetAmountFilled"])
                    exchange_ts = TimestampNs.from_ns_since_epoch(
                        int(trade["ts"]) * 1000000000
                    )
                    fee_ccy = "USDC"
                    side = direction_to_side_str(order_direction)
                    eeid = EEID.make(0)

                    quote_amount = Decimal(str(trade["quoteAssetAmountFilled"]))
                    price = quote_amount / quantity

                    trade_obj = Trade(
                        record_id=0,
                        trade_id="",
                        account=self.conn.config.account or self.conn.config.public_key,
                        eeid=eeid,
                        exchange_timestamp=exchange_ts,
                        exchange="drft",
                        symbol=instrument,
                        portfolio="",
                        strategy="",
                        side=side,
                        price=price,
                        quantity=quantity,
                        open_close=OpenClose.unknown,
                        fee=fee,
                        fee_currency=fee_ccy,
                        exchange_trade_id=fill_record_id,
                        trader_name="",
                        liquidity_indicator=liquidity,
                        execution_process="",
                        client_process="",
                        execution_client_id=0,
                        order_id=0,
                        exchange_order_id=order_id,
                        algo_id=0,
                        order_type=OrderType.UNKNOWN,
                        fx_base_currency=Decimal(0),
                        fx_base_currency_ts=TimestampNs.now(),
                        fx_quote_currency=Decimal(0),
                        fx_quote_currency_ts=TimestampNs.now(),
                        fx_fee_currency=Decimal(0),
                        fx_fee_currency_ts=TimestampNs.now(),
                    )
                    trades.append(trade_obj)
                except Exception as e:
                    import traceback

                    traceback.print_exc()
                    logger.error(f"Error processing trade {trade}: {str(e)}")
                    continue

            if trades:
                yield trades

            if (
                len(trades_raw) < page_limit
                or TimestampNs.from_datetime(poll_start_time) > exchange_ts
                or not next_page
            ):
                has_more = False


class OrderStatus(SerialisableEnum):
    OPEN = auto()
    REJECTED = auto()
    CANCELLED = auto()
    EXPIRED = auto()
    # PENDING = auto()


class OrderTrade:
    def __init__(
        self,
        trade_id: str,
        exec_price: Decimal,
        exec_qty: Decimal,
        liquidity: Literal["Maker", "Taker"],
        exch_timestamp: TimestampNs,
    ):
        self.trade_id = trade_id
        self.exec_price = exec_price
        self.exec_qty = exec_qty
        self.liquidity = liquidity
        self.exch_timestamp = exch_timestamp


class Order:
    def __init__(
        self,
        received_at: TimestampNs,
        auros_order_id: Optional[int],
        drift_user_order_id: Optional[int],
        drift_order_id: Optional[int],
        price: Decimal,
        qty: Decimal,
        side: Side,
        order_type: OrderType,
        symbol: str,
        slot: int,
        status: OrderStatus = OrderStatus.OPEN,
    ):
        self.received_at = received_at
        self.auros_order_id = auros_order_id
        self.drift_user_order_id = drift_user_order_id
        self.drift_order_id = drift_order_id
        self.price: Decimal = price
        self.qty: Decimal = qty
        self.side: Side = side
        self.order_type: OrderType = order_type
        self.symbol: str = symbol

        # the actual slot of the order placement will be greater than or equal to self.slot
        self.slot: int = slot
        self.place_tx_sig: str = ""
        self.place_tx_confirmed: bool = False

        self.drift_market_index: Optional[int] = None
        self.drift_market_type: Optional[MarketType] = None
        self.price_mult: int = 0
        self.qty_mult: int = 0

        self.total_executed_qty: Decimal = Decimal(0)
        self.last_update: TimestampNs = TimestampNs.now()
        self.status: OrderStatus = status
        self.reason: str = ""

        self.seen_trades_id = set()
        self.trades: List[OrderTrade] = []

        self.last_order_action_record_poll_success_at: TimestampNs = None
        self.finalised_at: TimestampNs = None

    def fill_market(
        self, market_index: int, market_type: str | MarketType, client: DriftClient
    ):
        self.drift_market_index = market_index
        if equal_drift_enum_str(market_type, "Perp"):
            self.qty_mult = BASE_PRECISION
            self.price_mult = PRICE_PRECISION
            self.drift_market_type = "perp"
        elif equal_drift_enum_str(market_type, "Spot"):
            spot = client.get_spot_market_account(self.drift_market_index)
            self.qty_mult = pow(10, spot.decimals)
            self.price_mult = PRICE_PRECISION
            self.drift_market_type = "spot"
        else:
            raise Exception(f"Unknown market type {market_type}")

    def is_finalised(self):
        return self.status != OrderStatus.OPEN


__all__ = [
    "decode_name",
    "equal_drift_enum",
    "equal_drift_enum_str",
    "convert_to_number",
    "direction_to_side",
    "DriftApi",
    "OrderStatus",
    "OrderTrade",
    "Order",
]
