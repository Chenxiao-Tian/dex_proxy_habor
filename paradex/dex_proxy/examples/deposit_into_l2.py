import aiohttp
import asyncio
import time

host = 'localhost'

'''
/private/approve-token
/private/withdraw
/private/withdraw-from-l2
/private/transfer-from-l1-bridge-to-wallet
/private/deposit-into-l2
/private/transfer-to-l2-trading
/private/get-l2-balance
/private/get-socialized-loss-factor
'''
async def deposit(session, amount):
    data = {
        'client_request_id': str(int(time.time() * 1e9)),
        'symbol': 'USDC',
        'amount': str(amount),
        'gas_limit': 5e5,
        'gas_price_wei': 25e9
    }

    async with session.post(f'http://{host}:1958/private/deposit-into-l2', json=data) as response:
        status = response.status
        print(f'Received status {status}')
        text = await response.text()
        print(f'Received text: {text}')


async def main():
    async with aiohttp.ClientSession() as session:
        print('deposit $10...')
        await deposit(session, 10)
        print('Test DONE')


asyncio.get_event_loop().run_until_complete(main())
