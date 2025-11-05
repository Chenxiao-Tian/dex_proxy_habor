# from pantheon.market_data_types import InstrumentId

from common.types import Ccy
import asyncio
import copy
from typing import Generic, TypeVar

T = TypeVar("T")

# FUNGIBLE_USD_CCY = {Ccy.USD, Ccy.USDC}

# FUNGIBLE_CCY_GROUPS = {
#     Ccy.USD: {Ccy.USD, Ccy.USDC, Ccy.CUSD},
#     Ccy.ETH: {Ccy.ETH, Ccy.WETH},
#     Ccy.BTC: {Ccy.BTC, Ccy.GBTC},
# }


# def get_iid_from_index(index: str) -> InstrumentId:
#     # index: FX-FLIP/USDT=bina
#     symbol, exchange = index.split("=")
#     return InstrumentId(exchange, symbol)


def get_base_and_quote(symbol: str) -> tuple[Ccy, Ccy]:
    # type | symbol | expiry
    # symbol = symbol.split("=")
    _, pair = symbol.split("-")
    base, quote = pair.split("/")
    return Ccy(base), Ccy(quote)


# def get_fungible_symbol_group(ccy: Ccy):
#     for k, group in FUNGIBLE_CCY_GROUPS.items():
#         if ccy in group:
#             return k

#     return ccy


class AwaitableVariable(Generic[T]):
    """This is a 1-element, single-reader, single-writer variable.

    If the value is not updated since the last 'get', the reader will block
    until new value is provided"""

    def __init__(self, copy_on_notify: bool = True):
        self.__event = asyncio.Event()
        self.__copy_on_notify = copy_on_notify
        self.__value: T | None = None
        self.__waiting = False

    def put(self, value: T):
        self.__value = value
        self.__event.set()

    async def get(self) -> T | None:
        assert self.__waiting == False, "Only one coroutine can wait for the variable"
        self.__waiting = True
        try:
            await self.__event.wait()
        finally:
            self.__waiting = False
            self.__event.clear()

        if self.__copy_on_notify:
            return copy.deepcopy(self.__value)
        else:
            return self.__value


class BroadcastAwaitableVariable:
    """This is a 1-element, multi-reader, multi-writer variable. It is not threadsafe."""

    def __init__(self, init=None, copy_on_notify: bool = True):
        """
        :param init: The initial value of the variable
        :param copy_on_notify: True if waiters should be given a copy of the
             value rather than a reference
        """
        self.__value = init
        self.__copy_on_notify = copy_on_notify
        self.__waiters = []  # [(fn, AwaitableVariable)]

    def set(self, value):
        """Set the value of the variable. If the variable is already equal to
        the value, the update is discarded (i.e., no listeners notified)."""

        if value != self.__value:
            self.__value = value
            # Split the waiters into two groups: those who will continue to
            # wait (sleepers), and those who will be notified (wakers).
            wakers = []
            sleepers = []
            for fn, event in self.__waiters:
                if fn(self.__value):
                    wakers.append(event)
                else:
                    sleepers.append((fn, event))
            self.__waiters = sleepers
            for waker in wakers:
                waker.put(self.__value)

    def get(self):
        """Return the current value immediately."""
        return self.__value

    async def get_next(self):
        """Return the new value when next it is set. A "set" to the same value
        does not count."""
        current = copy.deepcopy(self.__value)
        return await self.__get_wait(lambda v: v != current)

    async def get_when_equal(self, value):
        """Return the new value when it is equal to value. The condition is
        evaluated immediately and will return if variable is currently equal to
        value."""
        return await self.__get_wait(lambda v: v == value)

    async def get_when_next_equal(self, value):
        """Return the new value when it is equal to value. The condition will
        be evaluated the next time the variable is set to a new (different)
        value."""
        return await self.__get_wait_next(lambda v: v == value)

    async def get_when_oneof(self, *valid_values):
        """Return the new value when it is equal to one of valid_values. If no
        valid_values are supplied, return immediately. The condition is
        evaluated immediately and will return if variable is currently a valid
        value."""
        if len(valid_values) == 0:
            return self.__value
        return await self.__get_wait(lambda v: v in valid_values)

    async def get_when_next_oneof(self, *valid_values):
        """Return the new value when it is equal to one of valid_values. If no
        valid_values are supplied, return immediately. The condition will be
        evaluated the next time the variable is set to a new (different)
        value."""
        if len(valid_values) == 0:
            return self.__value
        return await self.__get_wait_next(lambda v: v in valid_values)

    async def get_when_noneof(self, *invalid_values):
        """Return the new value when it is not equal to one of invalid_values.
        If no invalid_values are supplied, return immediately."""
        if len(invalid_values) == 0:
            return self.__value
        return await self.__get_wait(lambda v: v not in invalid_values)

    async def get_when_next_noneof(self, *invalid_values):
        """Return the new value when it is not equal to one of invalid_values.
        If no invalid_values are supplied, return immediately."""
        if len(invalid_values) == 0:
            return self.__value
        return await self.__get_wait_next(lambda v: v not in invalid_values)

    async def get_when_true(self, *truth_fns):
        """Return the new value when any of truth_fns(value) evaluates to True.
        If no truth_fns are supplied, return immediately. The truth_fns are
        evaluated immediately and will return if the variable's current vaule
        matches."""
        if len(truth_fns) == 0:
            return self.__value
        return await self.__get_wait(lambda v: any([fn(v) for fn in truth_fns]))

    async def get_when_next_true(self, *truth_fns):
        """Return the new value when any of truth_fns(value) evaluates to True.
        If no truth_fns are supplied, return immediately. The functions will be
        evaluated when the variable is set to a new (different) value."""
        if len(truth_fns) == 0:
            return self.__value
        return await self.__get_wait_next(lambda v: any([fn(v) for fn in truth_fns]))

    async def __get_wait_next(self, fn):
        event = AwaitableVariable(copy_on_notify=self.__copy_on_notify)
        self.__waiters.append((fn, event))
        return await event.get()

    async def __get_wait(self, fn):
        if fn(self.__value):
            if self.__copy_on_notify:
                return copy.deepcopy(self.__value)
            else:
                return self.__value
        else:
            return await self.__get_wait_next(fn)
