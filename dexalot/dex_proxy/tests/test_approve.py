import aiohttp
import asyncio
import time

host = 'dev-sng-build1.kdev'


async def approve(session, symbol, amount):
    data = {
        'client_request_id': str(int(time.time() * 1e9)),
        'symbol': symbol,
        'amount': str(amount),
        'gas_price_wei': 25e9
    }
    async with session.post(f'http://{host}:1957/private/approve-token', json=data) as response:
        status = response.status
        print(f'Received status {status}')
        text = await response.text()
        print(f'Received text: {text}')


async def main():
    async with aiohttp.ClientSession() as session:
        print('Approving 1000 ALOT...')
        await approve(session, 'ALOT', 1000)

        print('Test DONE')


asyncio.get_event_loop().run_until_complete(main())
