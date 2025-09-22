import pprint
import requests
import asyncio

from eth_account import Account
from web3 import Web3, HTTPProvider
import json


async def main():
    orderbook_contract_addr = "0x05e6f736b5dedd60693fa806ce353156a1b73cf3"  # CHOG/MON
    price = "0.00000283"
    size = "10000"

    # Deposit funds using the dex proxy handler
    host = "http://localhost"
    port = "1958"
    deposit_endpoint = "/private/deposit"

    # Calculate required margin for the order
    order_value = float(price) * float(size)
    margin_amount = str(order_value * 2)  # 2x margin for safety

    deposit_data = {
        "amount": margin_amount,
        "currency": "MON"  # Required field
    }
    deposit_response = requests.post(url=host + ":" + port + deposit_endpoint, json=deposit_data)
    print(f"Deposit status: {deposit_response.status_code}")
    pprint.pprint(deposit_response.json())
    assert deposit_response.status_code == 200

    await asyncio.sleep(6)

    endpoint = "/private/create-order"

    data = {
        "symbol": orderbook_contract_addr,
        "side": "BUY",
        "price": price,
        "quantity": size,
        "order_type": "LIMIT",
        "client_order_id": "123"
    }
    response = requests.post(url=host + ":" + port + endpoint, json=data)
    print(response.status_code)
    pprint.pprint(response.json())
    assert response.status_code == 200
    assert response.json()['status'] == 'OPEN'


if __name__ == "__main__":
    asyncio.run(main())
