from abc import ABC, abstractmethod
from typing import List, Tuple, Optional


class MDSource(ABC):
    @abstractmethod
    def get_book(self, symbol: str, depth: int = 5) -> Optional[dict]:
        """Fetch market depth/book data"""
        pass
