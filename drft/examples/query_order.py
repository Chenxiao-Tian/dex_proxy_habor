import pprint
import requests

host = "http://localhost"
port = "1958"
endpoint = "/public/order"

data = {
    "client_order_id": "470",
}

response = requests.get(url=host + ":" + port + endpoint, params=data)
print(response.status_code)
pprint.pprint(response.json())
