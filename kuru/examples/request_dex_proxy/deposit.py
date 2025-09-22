import pprint
import requests
import asyncio
import json

async def main():
    """Example showing how to deposit funds using the dex proxy handler"""
    
    host = "http://localhost"
    port = "1958"
    endpoint = "/private/deposit"

    # Amount to deposit and currency type
    amount = "100.0"
    currency = "MON"  # Can be "USDC" or "MON"

    data = {
        "amount": amount,
        "currency": currency  # Required field
    }
    
    print(f"Depositing {amount} {currency} to margin account")
    
    response = requests.post(url=host + ":" + port + endpoint, json=data)
    
    print(f"Deposit status: {response.status_code}")
    pprint.pprint(response.json())
    
    if response.status_code == 200:
        result = response.json()
        print(f"Successfully deposited {result.get('amount')} {result.get('currency')} to margin account")
        print(f"Transaction hash: {result.get('tx_hash')}")
        print(f"Block number: {result.get('block_number')}")
    else:
        print("Failed to deposit")

if __name__ == "__main__":
    asyncio.run(main())