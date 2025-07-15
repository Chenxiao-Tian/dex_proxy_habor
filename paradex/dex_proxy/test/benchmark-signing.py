import time
import requests


ITERS = 2000

url = "http://localhost:1958/private/order-signature"

data = {
    "order_creation_ts_ms": 1684862276499,
    "market": "BTC-USD-PERP",
    "side": "BUY",
    "type": "LIMIT",
    "size": "2155122251.55151",
    "price": "14142155151511.11112"
}

start = time.time()
for i in range(ITERS):
    response = requests.post(url, json=data)
end = time.time()

print("Average signature request: {}ms".format(((end-start)*1000) / ITERS))
