import random
from decimal import Decimal
from typing import Optional

class OrderGenerator:
    def generate_gtc_order_data(self, account: str, client_order_id, high_price, symbol: Optional[str] = "SOL-PERP",
                                side: Optional[str] = "SELL"):
        if client_order_id is None:
            client_order_id = str(rand_id())

        data = {
            "account": account,
            "price": str(Decimal(high_price).quantize(Decimal('0.000001'))),
            "quantity": "0.01",
            "client_order_id": client_order_id,
            "side": side,
            "order_type": "GTC_POST_ONLY",
            "symbol": symbol,
        }
        return data


    def generate_ioc_order_data(self, account: str, client_order_id, price, symbol: Optional[str] = "SOL-PERP",
                                side: Optional[str] = "SELL"):
        if client_order_id is None:
            client_order_id = str(rand_id())

        data = {
            "account": account,
            "price": str(Decimal(price).quantize(Decimal('0.000001'))),
            "quantity": "0.01",
            "client_order_id": client_order_id,
            "side": side,
            "order_type": "IOC",
            "symbol": symbol,
        }
        return data

def rand_id(multiplier: int = 100_000) ->  int:
    return int(random.random() * multiplier)
