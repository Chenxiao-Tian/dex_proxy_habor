import pprint
import requests
import asyncio
import json

async def main():
    """Complete example showing margin balance management flow"""
    
    host = "http://localhost"
    port = "1958"
    base_url = f"{host}:{port}"

    print("=== Margin Balance Management Flow ===\n")

    # Step 1: Check current margin balance
    print("1. Checking current margin balance...")
    margin_response = requests.get(f"{base_url}/public/margin")
    print(f"Status: {margin_response.status_code}")
    if margin_response.status_code == 200:
        margin_data = margin_response.json()
        current_balance = margin_data.get('unified_margin', {}).get('total_collateral', 0)
        print(f"Current margin balance: {current_balance} USDC")
    pprint.pprint(margin_response.json())
    print()

    # Step 2: Deposit funds
    print("2. Depositing funds...")
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

    # Step 3: Check margin balance after deposit
    print("3. Checking margin balance after deposit...")
    margin_response_after = requests.get(f"{base_url}/public/margin")
    print(f"Status: {margin_response_after.status_code}")
    if margin_response_after.status_code == 200:
        margin_data_after = margin_response_after.json()
        new_balance = margin_data_after.get('unified_margin', {}).get('total_collateral', 0)
        print(f"New margin balance: {new_balance} USDC")
    pprint.pprint(margin_response_after.json())
    print()
    return
    # Step 4: Withdraw funds
    print("4. Withdrawing funds...")
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
    print("5. Verifying margin balance is cleared...")
    final_response = requests.get(f"{base_url}/public/margin")
    print(f"Status: {final_response.status_code}")
    if final_response.status_code == 200:
        final_data = final_response.json()
        final_balance = final_data.get('unified_margin', {}).get('total_collateral', 0)
        print(f"Final margin balance: {final_balance} USDC")
    pprint.pprint(final_response.json())

    print("\n=== Margin Balance Management Flow Complete ===")

if __name__ == "__main__":
    asyncio.run(main())