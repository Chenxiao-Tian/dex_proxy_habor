import random

import requests
from web3 import Web3

# http_testnet_url = "https://goerli.infura.io/v3/d3bf8a4fe2744587bf47459446b7f170"
# w3_http = Web3(Web3.HTTPProvider(http_testnet_url))


def approve(client_request_id: str):
    # gas_price = w3_http.eth.gas_price
    # print(gas_price)

    gas_price_used = 10000000
    # print(gas_price_used)

    url = "http://localhost:1958/private/approve-token"
    data = {
        "client_request_id": str(client_request_id),
        "symbol": "0x9151434b16b9763660705744891fA906F660EcC5",
        "amount": "1",
        "gas_price_wei": gas_price_used,
    }

    response = requests.post(url=url, json=data)
    print(response.status_code)
    print(response.json())


if __name__ == "__main__":
    approve("approve_" + str(int(random.random() * 1000)))