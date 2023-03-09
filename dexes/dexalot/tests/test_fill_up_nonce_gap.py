import aiohttp
import asyncio

host = 'dev-sng-build1.kdev'


async def fill_up_nonce_gap(session):
    data = {'env': 'fuji-multi-subnet', 'nonce': 100, 'gas_price_wei': int(5e9)}
    async with session.post(f'http://{host}:1957/private/fill-up-nonce-gap', json=data) as response:
        status = response.status
        print(f'Received status {status}')
        text = await response.text()
        print(f'Received text: {text}')


async def main():
    async with aiohttp.ClientSession() as session:
        print('Filling up nonce gap...')
        await fill_up_nonce_gap(session)

        print('Test DONE')


asyncio.get_event_loop().run_until_complete(main())
