import pprint
import requests

if __name__ == "__main__":
    host = "http://localhost"
    port = "1958"
    endpoint = "/public/orders"

    response = requests.get(url=host + ":" + port + endpoint)
    print(response.status_code)
    pprint.pprint(response.json())
