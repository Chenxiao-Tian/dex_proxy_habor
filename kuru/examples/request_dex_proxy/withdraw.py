import pprint
import requests
import asyncio
import json

async def main():
    """Example showing how to withdraw funds using the dex proxy handler"""
    
    host = "http://localhost"
    port = "1958"
    endpoint = "/private/withdraw"

    # Withdraw specific currency (required)
    currency = "MON"  # Can be "USDC" or "MON"
    data = {
        "currency": currency  # Required field
    }
    response = requests.post(url=host + ":" + port + endpoint, json=data)
    
    print(f"Withdraw status: {response.status_code}")
    pprint.pprint(response.json())
    
    if response.status_code == 200:
        result = response.json()
        if result.get("status") == "withdrawn":
            print(f"Successfully withdrew {result.get('withdrawn_amount')} {result.get('currency')} from margin account")
            print(f"Transaction hash: {result.get('tx_hash')}")
        elif result.get("status") == "already_empty":
            print(f"Balance was already zero for {result.get('currency')}")
    else:
        print("Failed to withdraw")

if __name__ == "__main__":
    asyncio.run(main())