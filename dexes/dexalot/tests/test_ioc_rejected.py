import aiohttp
import asyncio
import time

async def insert(session):
    data = {
        'client_order_id': str(time.time_ns()),
        'symbol': 'ALOT/AVAX',
        'price': '0.21',
        'qty': '100',
        'side': 'SELL',
        'type1': 1,
        'type2': 2,
        'timeout': 10
    }

    async with session.post('http://dev-sng-both0.kdev:1957/private/insert-order', json=data) as response:
        status = response.status
        print(f'Received status {status}')
        text = await response.text()
        print(f'Received text: {text}')

async def main():
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect('ws://dev-sng-both0.kdev:1957/private/ws') as ws:
            sub = {
                'id': 1,
                'jsonrpc': '2.0',
                'method': 'subscribe',
                'params': {'channel': 'ORDER'}
            }
            print('Subscription request: ', sub)
            await ws.send_json(sub)

            sub_reply = await ws.receive_json()
            print('Subscription reply: ', sub_reply)

            await insert(session)

            print('Test DONE')


asyncio.run(main())
