import logging
import pprint
import requests
import asyncio

from eth_account import Account
from web3 import Web3, HTTPProvider
import json


async def main():
    orderbook_contract_addr = "0xd3af145f1aa1a471b5f0f62c52cf8fcdc9ab55d3"  # MON/USDC
    price = "0.85"  # Price in USDC per MON
    size = "10.0"   # Amount of MON to sell

    # Deposit funds using the dex proxy handler
    host = "http://localhost"
    port = "1958"
    deposit_endpoint = "/private/deposit"

    # Deposit MON to sell
    deposit_data = {
        "amount": size,
        "currency": "MON"  # Required field - depositing MON to sell
    }
    deposit_response = requests.post(url=host + ":" + port + deposit_endpoint, json=deposit_data)
    print(f"Deposit status: {deposit_response.status_code}")
    pprint.pprint(deposit_response.json())
    assert deposit_response.status_code == 200

    endpoint = "/private/create-order"
    size = '10.0'
    data = {
        "symbol": orderbook_contract_addr,
        "side": "SELL",  # Selling MON to get USDC
        "price": price,
        "quantity": size,
        "order_type": "LIMIT",
        "client_order_id": "sell_mon_123"
    }
    response = requests.post(url=host + ":" + port + endpoint, json=data)
    print(response.status_code)
    pprint.pprint(response.json())
    assert response.status_code == 200
    assert response.json()['status'] == 'OPEN'


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    asyncio.run(main())