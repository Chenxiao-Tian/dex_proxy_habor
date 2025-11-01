import pprint
import requests

def main():

    client_order_id = "123"
    host = "http://localhost"
    port = "1958"
    endpoint = f"/public/order?client_order_id={client_order_id}"

    response = requests.get(url=host + ":" + port + endpoint)
    print(response.status_code)
    pprint.pprint(response.json())

if __name__ == "__main__":
    main()