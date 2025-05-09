import random

import requests
from web3 import Web3

# http_testnet_url = "https://goerli.infura.io/v3/d3bf8a4fe2744587bf47459446b7f170"
# w3_http = Web3(Web3.HTTPProvider(http_testnet_url))


def withdraw(client_request_id: str):
    # gas_price = w3_http.eth.gas_price
    # print(gas_price)

    gas_price_used = 10000000
    # print(gas_price_used)

    url = "http://localhost:1958/private/withdraw"
    data = {
        "client_request_id": str(client_request_id),
        "symbol": "ETH",
        "address_to": "0x52c5233d3d12e9d5522759ace8b551d926b797d1",
        "amount": "0.01",
        'gas_limit': 100000,
        "gas_price_wei": gas_price_used,
    }

    response = requests.post(url=url, json=data)
    print(response.status_code)
    print(response.json())


if __name__ == "__main__":
    withdraw("withdraw_" + str(int(random.random() * 1000)))