import time
import requests


token = requests.post(
    "http://localhost:1958/private/exchange-token", json={}).json()['token']

headers = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "Authorization": f"Bearer {token}"
}

dex_proxy_order = {
    "order_creation_ts_ms": int(time.time()*1000),
    "market": "BTC-USD-PERP",
    "side": "BUY",
    "type": "LIMIT",
    "size": "1.1",
    "price": "60000.5"
}

signature = requests.post("http://localhost:1958/private/order-signature",
                          json=dex_proxy_order).json()['signature']
order = {
    "instruction": "GTC",
    "market": dex_proxy_order["market"],
    "price": dex_proxy_order["price"],
    "side": dex_proxy_order["side"],
    "size": dex_proxy_order["size"],
    "signature": signature,
    "signature_timestamp": dex_proxy_order["order_creation_ts_ms"],
    "type": "LIMIT",
}

response = requests.post(
    "https://api.testnet.paradex.trade/v1/orders", headers=headers, json=order).json()

assert response['status'] == "NEW"
print(response)
