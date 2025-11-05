from abc import ABC, abstractmethod
from typing import Protocol
from ..dto.book import Book


class PriceModel(ABC):
    @abstractmethod
    def compute(self, book: Book) -> float:
        """Compute a price based on the given book"""
        pass
