from ..dto.book import Book
from typing import Optional


class MidPriceModel:
    def compute(self, book: Book) -> Optional[float]:
        return book.mid_price
