import pprint
import requests

host = "http://localhost"
port = "1958"
endpoint = "/private/deposit-token"

data = {"token": "SOL", "amount": "0.01"}

response = requests.post(url=host + ":" + port + endpoint, json=data)
print(response.status_code)
pprint.pprint(response.json())
