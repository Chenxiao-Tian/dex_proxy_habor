import logging
import pprint
import requests
import asyncio
import time
from decimal import Decimal


async def get_balances(base_url):
    """Get current wallet and exchange balances"""
    response = requests.get(f"{base_url}/public/balance")
    if response.status_code != 200:
        raise Exception(f"Failed to get balances: {response.text}")
    return response.json()


async def deposit_to_exchange(base_url, amount, currency):
    """Deposit funds to exchange wallet"""
    deposit_data = {"amount": str(amount), "currency": currency}
    response = requests.post(f"{base_url}/private/deposit", json=deposit_data)
    if response.status_code != 200:
        raise Exception(f"Failed to deposit {amount} {currency}: {response.text}")
    print(f"✅ Deposited {amount} {currency}")
    return response.json()


async def withdraw_from_exchange(base_url, currency):
    """Withdraw all funds from exchange wallet"""
    withdraw_data = {"currency": currency}
    response = requests.post(f"{base_url}/private/withdraw", json=withdraw_data)
    if response.status_code != 200:
        raise Exception(f"Failed to withdraw {currency}: {response.text}")
    print(f"✅ Withdrew all {currency}")
    return response.json()


async def cancel_all_orders(base_url):
    """Cancel all live orders"""
    response = requests.delete(f"{base_url}/private/cancel-all-orders")
    if response.status_code != 200:
        print(f"⚠️ Failed to cancel all orders: {response.text}")
        return False
    result = response.json()
    cancelled = result.get('cancelled', [])
    print(f"✅ Cancelled {len(cancelled)} orders: {cancelled}")
    return True


async def place_order(base_url, symbol, side, price, quantity, client_order_id):
    """Place a trading order"""
    order_data = {
        "symbol": symbol,
        "side": side,
        "price": str(price),
        "quantity": str(quantity),
        "order_type": "LIMIT",
        "client_order_id": client_order_id
    }
    response = requests.post(f"{base_url}/private/create-order", json=order_data)
    if response.status_code != 200:
        raise Exception(f"Failed to place order: {response.text}")
    print(f"✅ Placed {side} order: {quantity} at {price}")
    return response.json()


async def main():
    """Portfolio balancing example - maintain 50/50 USD value split between USDC and MON"""
    
    host = "http://localhost"
    port = "1958"
    base_url = f"{host}:{port}"
    
    # Configuration
    TARGET_USDC_PERCENTAGE = Decimal(0.5)  # 50% USDC
    TARGET_MON_PERCENTAGE = Decimal(0.5)   # 50% MON
    MON_USD_PRICE = Decimal("3.2461")
    USDC_USD_PRICE = Decimal("1.0")  # USDC is 1:1 with USD
    MON_USDC_MARKET = "0xd3af145f1aa1a471b5f0f62c52cf8fcdc9ab55d3"  # MON/USDC market
    REBALANCE_THRESHOLD = Decimal("0.05")  # Rebalance if allocation differs by more than 5%
    
    print("=== Portfolio USD Balancing ===\n")
    
    # Step 1: Cancel all existing orders
    print("1. Cancelling all existing orders...")
    await cancel_all_orders(base_url)
    await asyncio.sleep(2)  # Wait for cancellations to process
    
    # Step 2: Get current balances
    print("\n2. Checking current balances...")
    balance_data = await get_balances(base_url)
    
    # Extract exchange wallet balances
    exchange_balances = {}
    for item in balance_data.get('balances', {}).get('exchange_wallet', []):
        exchange_balances[item['symbol']] = Decimal(str(item['balance']))
    
    usdc_balance = exchange_balances.get('USDC', Decimal('0'))
    mon_balance = exchange_balances.get('MON', Decimal('0'))
    
    print(f"Exchange wallet balances:")
    print(f"  USDC: {usdc_balance}")
    print(f"  MON: {mon_balance}")
    
    # Step 3: Calculate USD values
    usdc_usd_value = usdc_balance * USDC_USD_PRICE
    mon_usd_value = mon_balance * MON_USD_PRICE
    total_usd_value = usdc_usd_value + mon_usd_value
    
    print(f"\nUSD Values:")
    print(f"  USDC: ${usdc_usd_value}")
    print(f"  MON: ${mon_usd_value}")
    print(f"  Total: ${total_usd_value}")
    
    if total_usd_value == 0:
        print("❌ No funds in exchange wallet to balance")
        return
    
    # Step 4: Calculate current allocation percentages
    current_usdc_percentage = usdc_usd_value / total_usd_value
    current_mon_percentage = mon_usd_value / total_usd_value
    
    print(f"\nCurrent allocation:")
    print(f"  USDC: {current_usdc_percentage:.1%}")
    print(f"  MON: {current_mon_percentage:.1%}")
    
    # Step 5: Check if rebalancing is needed
    usdc_deviation = abs(current_usdc_percentage - TARGET_USDC_PERCENTAGE)
    mon_deviation = abs(current_mon_percentage - TARGET_MON_PERCENTAGE)
    
    print(f"\nTarget allocation:")
    print(f"  USDC: {TARGET_USDC_PERCENTAGE:.1%}")
    print(f"  MON: {TARGET_MON_PERCENTAGE:.1%}")
    
    print(f"\nDeviation from target:")
    print(f"  USDC: {usdc_deviation:.1%}")
    print(f"  MON: {mon_deviation:.1%}")
    
    if usdc_deviation < REBALANCE_THRESHOLD and mon_deviation < REBALANCE_THRESHOLD:
        print("✅ Portfolio is already well balanced, no rebalancing needed")
        return
    
    # Step 6: Calculate target amounts
    target_usdc_usd = total_usd_value * TARGET_USDC_PERCENTAGE
    target_mon_usd = total_usd_value * TARGET_MON_PERCENTAGE
    
    target_usdc_amount = target_usdc_usd / USDC_USD_PRICE
    target_mon_amount = target_mon_usd / MON_USD_PRICE
    
    print(f"\nTarget amounts:")
    print(f"  USDC: {target_usdc_amount}")
    print(f"  MON: {target_mon_amount}")
    
    # Step 7: Determine rebalancing action
    usdc_diff = target_usdc_amount - usdc_balance
    mon_diff = target_mon_amount - mon_balance
    
    print(f"\nRebalancing needed:")
    print(f"  USDC: {usdc_diff:+}")
    print(f"  MON: {mon_diff:+}")
    
    # Step 8: Execute rebalancing trades with aggressive pricing
    print("\n8. Executing rebalancing trades with 10% aggressive pricing...")
    
    if usdc_diff > 0:
        # Need more USDC, sell MON for USDC
        mon_to_sell = abs(usdc_diff / MON_USD_PRICE)  # Convert USD difference to MON amount
        # Aggressive pricing: sell 10% below market price to ensure quick fill
        aggressive_price = MON_USD_PRICE * Decimal("0.9")  # 10% below market
        
        print(f"Selling {mon_to_sell} MON at {aggressive_price} USDC per MON (10% below market {MON_USD_PRICE})")
        order_id = f"rebalance_sell_{int(time.time())}"
        
        try:
            await place_order(base_url, MON_USDC_MARKET, "SELL", aggressive_price, mon_to_sell, order_id)
        except Exception as e:
            print(f"❌ Failed to place sell order: {e}")
            
    elif mon_diff > 0:
        # Need more MON, buy MON with USDC
        usdc_to_spend = abs(mon_diff * MON_USD_PRICE)  # Convert MON difference to USDC
        # Aggressive pricing: pay 10% above market price to ensure quick fill
        aggressive_price = MON_USD_PRICE * Decimal("1.1")  # 10% above market
        mon_to_buy = usdc_to_spend / aggressive_price  # Adjust quantity for higher price
        
        print(f"Buying {mon_to_buy} MON at {aggressive_price} USDC per MON (10% above market {MON_USD_PRICE})")
        order_id = f"rebalance_buy_{int(time.time())}"
        
        try:
            await place_order(base_url, MON_USDC_MARKET, "BUY", aggressive_price, mon_to_buy, order_id)
        except Exception as e:
            print(f"❌ Failed to place buy order: {e}")
    
    # Step 9: Wait and check final balances
    print("\n9. Waiting for trades to settle...")
    await asyncio.sleep(10)
    
    print("\n10. Final balance check...")
    final_balance_data = await get_balances(base_url)
    
    final_exchange_balances = {}
    for item in final_balance_data.get('balances', {}).get('exchange_wallet', []):
        final_exchange_balances[item['symbol']] = Decimal(str(item['balance']))
    
    final_usdc_balance = final_exchange_balances.get('USDC', Decimal('0'))
    final_mon_balance = final_exchange_balances.get('MON', Decimal('0'))
    
    final_usdc_usd = final_usdc_balance * USDC_USD_PRICE
    final_mon_usd = final_mon_balance * MON_USD_PRICE
    final_total_usd = final_usdc_usd + final_mon_usd
    
    if final_total_usd > 0:
        final_usdc_percentage = final_usdc_usd / final_total_usd
        final_mon_percentage = final_mon_usd / final_total_usd
        
        print(f"\nFinal balances:")
        print(f"  USDC: {final_usdc_balance} (${final_usdc_usd}) = {final_usdc_percentage:.1%}")
        print(f"  MON: {final_mon_balance} (${final_mon_usd}) = {final_mon_percentage:.1%}")
        print(f"  Total: ${final_total_usd}")
    
    print("\n=== Portfolio Balancing Complete ===")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())