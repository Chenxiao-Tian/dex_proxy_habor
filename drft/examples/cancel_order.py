import pprint
import requests

host = "http://localhost"
port = "1958"
endpoint = "/private/cancel-order"

data = {
    "account": "drift_test_0",
    "client_order_id": "470",
}

response = requests.delete(url=host + ":" + port + endpoint, params=data)
print(response.status_code)
pprint.pprint(response.json())
