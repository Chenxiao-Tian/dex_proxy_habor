from decimal import Decimal

from kuru_sdk import Orderbook
from web3 import Web3


class MarketData:
    def __init__(self):
        pass

    async def get_ioc_order_data(self, config_data_module, private_key_hex_module, orderbook_contract_addr):
        rpc_url = config_data_module.get("dex", {}).get("url", "")

        orderbook = Orderbook(
            Web3(Web3.HTTPProvider(rpc_url)),
            orderbook_contract_addr,
            private_key=private_key_hex_module,
        )

        [sells, buys] = await orderbook.get_l2_book()
        size = float(orderbook.market_params.min_size) / float(orderbook.market_params.size_precision)  # takin min size
        size_str = str(Decimal(size + size / 1000))
        price = str(sells[0][0])  # take highest price
        price_str = str(Decimal(price))

        data = {
            "symbol": orderbook_contract_addr,
            "side": "BUY",
            "price": price_str,
            "quantity": size_str,
            "order_type": "LIMIT",
            "client_order_id": "123"
        }
        return data

    async def get_gtc_order_data(self, config_data_module, private_key_hex_module, orderbook_contract_addr):
        rpc_url = config_data_module.get("dex", {}).get("url", "")

        orderbook = Orderbook(
            Web3(Web3.HTTPProvider(rpc_url)),
            orderbook_contract_addr,
            private_key=private_key_hex_module,
        )

        [sells, buys] = await orderbook.get_l2_book()
        size = float(orderbook.market_params.min_size) / float(orderbook.market_params.size_precision)  # takin min size
        size_str = str(Decimal(size + size / 1000))
        price = str(sells[-1][0] / 10)  # take lowest price diveded by 10
        price_str = str(Decimal(price))

        data = {
            "symbol": orderbook_contract_addr,
            "side": "BUY",
            "price": price_str,
            "quantity": size_str,
            "order_type": "LIMIT",
            "client_order_id": "123"
        }
        return data

