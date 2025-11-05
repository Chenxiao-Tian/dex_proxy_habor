import pprint
import requests
import random

host = "http://localhost"
port = "1958"
endpoint = "/private/create-order"

data = {
    "account": "drift_test_0",
    "price": "155.3",
    "quantity": "0.01",
    "client_order_id": str(int(random.random() * 100000)),
    "side": "SELL",
    "order_type": "GTC_POST_ONLY",
    "symbol": "SOL-PERP", # PSWP-SOL/USDC
}

response = requests.post(url=host + ":" + port + endpoint, json=data)
print(response.status_code)
pprint.pprint(response.json())
