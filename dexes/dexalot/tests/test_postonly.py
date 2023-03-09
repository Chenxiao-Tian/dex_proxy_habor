import aiohttp
import asyncio
import time

host = 'dev-sng-build1.kdev'


async def insert(session):
    data = {
        'client_order_id': str(int(time.time()*1e9)),
        'symbol': 'ALOT/USDC',
        'price': '3',
        'qty': '20',
        'side': 'BUY',
        'type1': 1,
        'type2': 3,
        'gas_price_wei': 5e9,
        'timeout': 10
    }

    async with session.post(f'http://{host}:1957/private/insert-order', json=data) as response:
        status = response.status
        print(f'Received status {status}')
        text = await response.text()
        print(f'Received text: {text}')


async def main():
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(f'ws://{host}:1957/private/ws') as ws:
            sub = {
                'id': 1,
                'jsonrpc': '2.0',
                'method': 'subscribe',
                'params': {
                    'channel': 'ORDER'}
            }
            print('Subscription request: ', sub)
            await ws.send_json(sub)
            sub_reply = await ws.receive_json()
            print('Subscription reply: ', sub_reply)

            for i in range(10):
                await insert(session)

            print('Test DONE')


asyncio.run(main())
