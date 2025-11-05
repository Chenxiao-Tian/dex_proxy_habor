import aiohttp
import asyncio
import time

_host = 'http://dev-sng-both1.kdev:11968'
host = 'http://localhost:1958'


async def order_sign(session):
    data = {
        'client_request_id': str(int(time.time() * 1e9)),
        'order_creation_ts_ms': int(time.time() * 1000),
        'orders': [{
            'coin': 'ETH',
            'is_buy': True,
            'sz': 0.2,
            'limit_px': 1100,
            'order_type': {"limit": {"tif": "Gtc"}},
            'reduce_only': False,
            'cloid': None
        }]
    }
    async with session.post(f'{host}/private/order-signature', json=data) as response:
        status = response.status
        print(f'Received status {status}')
        text = await response.text()
        print(f'Received text: {text}')


async def main():
    async with aiohttp.ClientSession() as session:
        await order_sign(session)
        print('Test DONE')


asyncio.get_event_loop().run_until_complete(main())
