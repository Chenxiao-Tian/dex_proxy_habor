import pprint
import requests

host = "http://localhost"
port = "1958"
endpoint = "/private/cancel-all-orders"

response = requests.delete(url=host + ":" + port + endpoint)
print(response.status_code)
pprint.pprint(response.json())
