import pprint
import requests

host = "http://localhost"
port = "1958"
endpoint = "/public/margin-data"

response = requests.get(url=host + ":" + port + endpoint)
print(response.status_code)
pprint.pprint(response.json())
