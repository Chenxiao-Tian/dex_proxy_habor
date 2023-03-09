import aiohttp
import asyncio
import time

host = 'dev-sng-build1.kdev'


async def main():
    async with aiohttp.ClientSession() as session:
        data = {
            'client_request_id': str(int(time.time() * 1e9)),
            'symbol': 'ALOT',
            'amount': '2',
            'gas_limit': 5e5,
            'gas_price_wei': 5e9
        }
        async with session.post(f'http://{host}:1957/private/remove-gas-from-tank', json=data) as response:
            status = response.status
            print(f'Received status {status}')

            text = await response.text()
            print(f'Received text: {text}')

            print('Test DONE')


asyncio.run(main())
