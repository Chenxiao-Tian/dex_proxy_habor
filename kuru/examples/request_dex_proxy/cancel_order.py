import pprint
import requests

def main():
    # Hard-coded parameters - users can edit these values
    client_order_id = "123"  # The client order ID of the order to cancel
    host = "http://localhost"
    port = "1958"
    endpoint = "/private/cancel-order"

    data = {
        "client_order_id": client_order_id
    }

    response = requests.delete(url=host + ":" + port + endpoint, json=data)
    print(response.status_code)
    pprint.pprint(response.json())

    # Check if cancellation was successful
    if response.status_code == 200:
        print(f"Order {client_order_id} cancellation initiated successfully")
    elif response.status_code == 404:
        print(f"Order {client_order_id} not found")
    else:
        print(f"Order cancellation failed with status: {response.status_code}")

if __name__ == "__main__":
    main()