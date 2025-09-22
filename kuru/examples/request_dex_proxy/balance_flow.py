import pprint
import requests
import asyncio
import json

async def main():
    """Complete example showing balance management flow"""
    
    host = "http://localhost"
    port = "1958"
    base_url = f"{host}:{port}"

    print("=== Balance Management Flow ===\n")

    # Step 1: Check current balances
    print("1. Checking current balances...")
    balance_response = requests.get(f"{base_url}/public/balance")
    print(f"Status: {balance_response.status_code}")
    if balance_response.status_code == 200:
        balance_data = balance_response.json()
        exchange_wallet = balance_data.get('balances', {}).get('exchange_wallet', [])
        for item in exchange_wallet:
            print(f"Exchange wallet balance: {item['balance']} {item['symbol']}")
    pprint.pprint(balance_response.json())
    print()

    # Step 2: Deposit funds
    input("2. Deposit funds?")
    deposit_data = {
        "amount": "50.0",  # 50 MON
        "currency": "MON"  # Required field
    }
    deposit_response = requests.post(f"{base_url}/private/deposit", json=deposit_data)
    print(f"Status: {deposit_response.status_code}")
    pprint.pprint(deposit_response.json())
    print()

    # Wait for transaction to settle
    await asyncio.sleep(5)

    # Step 3: Check balances after deposit
    input("3. Checking balances after deposit?")
    balance_response_after = requests.get(f"{base_url}/public/balance")
    print(f"Status: {balance_response_after.status_code}")
    if balance_response_after.status_code == 200:
        balance_data_after = balance_response_after.json()
        exchange_wallet_after = balance_data_after.get('balances', {}).get('exchange_wallet', [])
        for item in exchange_wallet_after:
            print(f"Exchange wallet balance: {item['balance']} {item['symbol']}")
    pprint.pprint(balance_response_after.json())
    print()

    # Step 4: Withdraw funds
    input("4. Withdraw funds?")
    withdraw_data = {
        "currency": "MON"  # Required field
    }
    withdraw_response = requests.post(f"{base_url}/private/withdraw", json=withdraw_data)
    print(f"Status: {withdraw_response.status_code}")
    pprint.pprint(withdraw_response.json())
    print()

    # Wait for transaction to settle
    await asyncio.sleep(5)

    # Step 5: Verify balance is cleared
    print("5. Verifying balance is cleared...")
    final_response = requests.get(f"{base_url}/public/balance")
    print(f"Status: {final_response.status_code}")
    if final_response.status_code == 200:
        final_data = final_response.json()
        exchange_wallet_final = final_data.get('balances', {}).get('exchange_wallet', [])
        for item in exchange_wallet_final:
            print(f"Final exchange wallet balance: {item['balance']} {item['symbol']}")
    pprint.pprint(final_response.json())

    print("\n=== Balance Management Flow Complete ===")

if __name__ == "__main__":
    asyncio.run(main())