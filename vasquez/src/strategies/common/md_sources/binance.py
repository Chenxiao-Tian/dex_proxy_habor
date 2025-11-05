import requests
from typing import Optional
from .md_source_base import MDSource
from ..dto.book import Book


class Binance(MDSource):
    BASE_URL = "https://api.binance.com"

    def get_book(self, symbol: str, depth: int = 5) -> Optional[Book]:
        endpoint = f"{self.BASE_URL}/api/v3/depth"
        params = {"symbol": symbol.upper(), "limit": depth}
        try:
            response = requests.get(endpoint, params=params)
            response.raise_for_status()
            data = response.json()

            bids = [(float(price), float(qty)) for price, qty in data["bids"]]
            asks = [(float(price), float(qty)) for price, qty in data["asks"]]

            return Book(bids, asks)

        except requests.RequestException as e:
            print(f"Error fetching book for {symbol}: {e}")
            return None
