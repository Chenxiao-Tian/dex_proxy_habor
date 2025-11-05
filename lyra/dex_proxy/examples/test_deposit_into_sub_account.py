import aiohttp
import asyncio
import time

host = 'localhost'


async def deposit(session, amount):
    data = {
        'client_request_id': str(int(time.time() * 1e9)),
        'symbol': 'WSTETH',
        'amount': str(amount)
    }

    async with session.post(f'http://{host}:1958/private/approve-deposit-to-subaccount', json=data) as response:
        status = response.status
        print(f'Received status {status}')
        text = await response.text()
        print(f'Received text: {text}')

    data = {
        'client_request_id': str(int(time.time() * 1e9)),
        'symbol': 'WSTETH',
        'amount': str(amount),
        'subaccount_id': '23741',
        'subaccount_type': 'SM'
    }

    async with session.post(f'http://{host}:1958/private/deposit-from-l2-to-subaccount', json=data) as response:
        status = response.status
        print(f'Received status {status}')
        text = await response.text()
        print(f'Received text: {text}')


async def main():
    async with aiohttp.ClientSession() as session:
        print('deposit 2...')
        await deposit(session, 2)
        print('Test DONE')


asyncio.get_event_loop().run_until_complete(main())
