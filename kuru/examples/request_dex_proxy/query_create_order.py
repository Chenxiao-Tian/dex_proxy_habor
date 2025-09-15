import pprint
import requests
import asyncio

from eth_account import Account
from web3 import Web3, HTTPProvider
import json

from kuru.util.margin import add_margin_balance

async def main():
    with open('../../kuru.local.config.json', 'r') as f:
        config_data = json.load(f)
        
    rpc_url = config_data['dex']['url']

    with(open('../../test-local-wallet.json')) as f:
        wallet_data = json.load(f)

    private_key = Account.decrypt(wallet_data, "")


    orderbook_contract_addr = "0x05e6f736b5dedd60693fa806ce353156a1b73cf3" # CHOG/MON
    price = "0.00000283"
    size = "10000"
    num_orders = 1

    await add_margin_balance(rpc_url, price, size, num_orders, private_key.hex())
    await asyncio.sleep(6)

    host = "http://localhost"
    port = "1958"
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
