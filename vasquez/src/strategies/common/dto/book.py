from typing import List, Tuple


class EmptyOrderBookError(Exception):
    pass


class Book:
    def __init__(
        self, bids: List[Tuple[float, float]], asks: List[Tuple[float, float]]
    ):
        self.bids = bids
        self.asks = asks

    def best_bid(self) -> Tuple[float, float]:
        if not self.bids:
            raise EmptyOrderBookError("No bids available in the order book")
        return self.bids[0]

    def best_ask(self) -> Tuple[float, float]:
        if not self.asks:
            raise EmptyOrderBookError("No asks available in the order book")
        return self.asks[0]

    @property
    def mid_price(self) -> float:
        bid, _ = self.best_bid()
        ask, _ = self.best_ask()
        return (bid + ask) / 2

    def __repr__(self):
        return f"<Book bids={len(self.bids)} asks={len(self.asks)}>"
