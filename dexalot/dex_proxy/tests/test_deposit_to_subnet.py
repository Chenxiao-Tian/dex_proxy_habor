import aiohttp
import asyncio
import time

host = 'dev-sng-build1.kdev'


async def deposit(session, symbol, amount):
    data = {
        'client_request_id': str(int(time.time() * 1e9)),
        'symbol': symbol,
        'amount': str(amount),
        'gas_limit': 5e5,
        'gas_price_wei': 25e9
    }
    async with session.post(f'http://{host}:1957/private/deposit-into-subnet', json=data) as response:
        status = response.status
        print(f'Received status {status}')
        text = await response.text()
        print(f'Received text: {text}')


async def main():
    async with aiohttp.ClientSession() as session:
        print('Depositing 1000 ALOT...')
        await deposit(session, 'ALOT', 1000)

        print('Test DONE')


asyncio.get_event_loop().run_until_complete(main())
