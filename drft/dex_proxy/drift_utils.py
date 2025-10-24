from enum import Enum
from typing import Dict, Tuple

from pantheon.timestamp_ns import TimestampNs
from dex_proxy.drift_api import MarketType, Order, OrderTrade

from driftpy.types import MarketType as DriftMarketType


class AccessMode(Enum):
    READONLY = "readonly"
    READWRITE = "readwrite"


def order_to_dict(order: Order) -> dict:
    return {
        "client_order_id": order.auros_order_id,
        "order_id": str(order.drift_order_id) if order.drift_order_id else "",
        "price": str(order.price),
        "quantity": str(order.qty),
        "total_exec_quantity": str(order.total_executed_qty),
        "last_update_timestamp_ns": order.last_update.get_ns_since_epoch(),
        "status": str(order.status.name),
        "reason": order.reason,
        "trades": [trade_to_dict(t) for t in order.trades],
        "order_type": str(order.order_type.name),
        "symbol": str(order.symbol),
        "side": str(order.side.name),
        "place_tx_sig": order.place_tx_sig,
    }


def full_order_to_dict(order: Order) -> dict:
    return {
        "auros_order_id": order.auros_order_id,
        "drift_user_order_id": order.drift_user_order_id,
        "drift_order_id": str(order.drift_order_id) if order.drift_order_id else "",
        "price": str(order.price),
        "qty": str(order.qty),
        "side": str(order.side.name),
        "order_type": str(order.order_type.name),
        "symbol": str(order.symbol),
        "slot": order.slot,
        "place_tx_sig": order.place_tx_sig,
        "place_tx_confirmed": order.place_tx_confirmed,
        "drift_market_index": order.drift_market_index,
        "drift_market_type": order.drift_market_type,
        "price_mult": order.price_mult,
        "qty_mult": order.qty_mult,
        "total_executed_qty": str(order.total_executed_qty),
        "last_update": str(order.last_update),
        "status": str(order.status.name),
        "reason": order.reason,
        "trades": [trade_to_dict(t) for t in order.trades],
        "received_at": str(order.received_at),
        "last_order_action_record_poll_success_at": (
            str(order.last_order_action_record_poll_success_at)
            if order.last_order_action_record_poll_success_at
            else ""
        ),
        "finalised_at": str(order.finalised_at) if order.finalised_at else "",
    }


def trade_to_dict(trade: OrderTrade) -> dict:
    return {
        "trade_id": trade.trade_id,
        "exec_price": str(trade.exec_price),
        "exec_quantity": str(trade.exec_qty),
        "liquidity": trade.liquidity,
        "exch_timestamp_ns": trade.exch_timestamp.get_ns_since_epoch(),
    }


def get_drift_market_type(market_type: MarketType) -> DriftMarketType:
    if market_type == "spot":
        return DriftMarketType.Spot()
    elif market_type == "perp":
        return DriftMarketType.Perp()
    else:
        raise Exception(f"Unknown market type {market_type}")


def classify_insert_error(error_message: str) -> str:
    if len(error_message) == 0:
        return "TRANSPORT_FAILURE"
    elif "Post-only order can immediately fill" in error_message:
        return "WOULD_TAKE"
    elif "UserOrderIdAlreadyInUse" in error_message:
        return "TRADING_RULES_BREACH"
    elif "OrderAmountTooSmall" in error_message:
        return "INVALID_PARAMETER"
    elif "InvalidOrderMinOrderSize" in error_message:
        return "INVALID_PARAMETER"
    elif "InsufficientCollateral" in error_message:
        return "INSUFFICIENT_FUNDS"
    elif "InsufficientFundsForRent" in error_message:
        return "INSUFFICIENT_FUNDS"

    return "EXCHANGE_REJECTION"


def should_send_cancel_order_error(error_message: str) -> bool:
    return (len(error_message) > 0
            and "Order not open" not in error_message
            and "This transaction has already been processed" not in error_message
            and "Unable to confirm transaction" not in error_message)


def classify_cancel_error(error_message: str) -> str:
    if "OrderDoesNotExist" in error_message:
        return "ORDER_NOT_FOUND"

    return "EXCHANGE_REJECTION"


def has_insert_failed(
    order: Order, mark_insert_failed_only_after_s: int, symbol: str, market: MarketType, min_slot: int, max_slot: int
) -> bool:
    return (
        order.drift_order_id is None
        and (TimestampNs.now() - order.received_at > mark_insert_failed_only_after_s * 1000_000_000)
        and order.symbol == symbol
        and order.drift_market_type == market
        and order.slot > min_slot
        and order.slot < max_slot
    )


def maybe_add_symbol_for_getting_order_record(
    symbol_market_to_min_slot: Dict[Tuple[str, str], int], symbol: str, market: MarketType, slot: int
):
    if (symbol, market) not in symbol_market_to_min_slot or symbol_market_to_min_slot[(symbol, market)] > slot:
        symbol_market_to_min_slot[(symbol, market)] = slot


def min_without_none(slot_1: int | None, slot_2: int | None) -> int | None:
    if slot_1 and slot_2:
        return min(slot_1, slot_2)

    return slot_1 if slot_1 else slot_2


def max_without_none(slot_1: int | None, slot_2: int | None) -> int | None:
    if slot_1 and slot_2:
        return max(slot_1, slot_2)

    return slot_1 if slot_1 else slot_2


def should_get_order_record(order: Order, start_polling_after_insert_s: int) -> bool:
    now = TimestampNs.now()
    return (not order.drift_order_id) and (now - order.received_at > start_polling_after_insert_s * 1000_000_000)


def should_get_order_action_records(order: Order, start_polling_after_insert_s: int, refetch_order_action_records_after_s: int) -> bool:
    now = TimestampNs.now()
    return (
        order.drift_order_id
        and (now - order.received_at > start_polling_after_insert_s * 1000_000_000)
        and (
            (not order.last_order_action_record_poll_success_at)
            or (now - order.last_order_action_record_poll_success_at > refetch_order_action_records_after_s * 1000_000_000)
        )
    )


def should_check_place_transaction(order: Order) -> bool:
    if order.drift_order_id:
        order.place_tx_confirmed = True

    return not order.place_tx_confirmed and len(order.place_tx_sig) > 0
