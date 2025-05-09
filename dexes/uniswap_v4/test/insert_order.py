import random
import requests
from web3 import Web3

http_url = "https://mainnet.infura.io/v3/d3bf8a4fe2744587bf47459446b7f170"
w3_http = Web3(Web3.HTTPProvider(http_url))


def insert(client_request_id: str):
    # gas_price = w3_http.eth.gas_price
    # print(gas_price)

    # gas_price_used = str(int(0.001 * w3_http.eth.gas_price))
    # print(gas_price_used)

    url = "http://localhost:1958/private/insert-order"
    data = {
        "client_request_id": str(client_request_id),
        "symbol": "AMM-ETH/USDT0-Pool3900",
        "base_ccy_qty": "0.002",
        "quote_ccy_qty": "3.5",
        "side": "SELL",
        "fee_rate": "500",
        "gas_price_wei": "1000",
        "timeout_s": 2
    }

    response = requests.post(url=url, json=data)
    print(response.status_code)
    print(response.json())


if __name__ == "__main__":
    insert("order_" + str(int(random.random() * 1000)))