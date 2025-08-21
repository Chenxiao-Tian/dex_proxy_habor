import random
import requests
from web3 import Web3

http_url = "https://mainnet.infura.io/v3/d3bf8a4fe2744587bf47459446b7f170"
w3_http = Web3(Web3.HTTPProvider(http_url))


def insert(client_request_id: str):
    # gas_price = w3_http.eth.gas_price
    # print(gas_price)

    gas_price_used = 174791000
    # print(gas_price_used)

    url = "http://dev-sng-both1:1958/private/insert-order"
    data = {
        "client_request_id": str(client_request_id),
        "dex": "v4",
        "symbol": "AMM-WETH/USDC-Pool935",
        "base_ccy_qty": "0.000022",
        "quote_ccy_qty": "0.088",
        "side": "SELL",
        "fee_rate": "300",
        "gas_price_wei": gas_price_used,
        "timeout_s": 2
    }

    response = requests.post(url=url, json=data)
    print(response.status_code)
    print(response.text)


if __name__ == "__main__":
    insert("order_" + str(int(random.random() * 1000)))