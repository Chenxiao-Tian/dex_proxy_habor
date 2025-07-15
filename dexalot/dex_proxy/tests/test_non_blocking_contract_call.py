import aiohttp
import asyncio
import time

host = 'dev-sng-build1.kdev'

async def insert(session, client_order_id, gas_price_wei):
    data = {
        'client_order_id': str(client_order_id),
        'symbol': 'ALOT/USDC',
        'price': '20',
        'qty': '2',
        'side': 'SELL',
        'type1': 1,
        'type2': 2,
        'gas_price_wei': gas_price_wei,
        'timeout': 10
    }

    async with session.post(f'http://{host}:1957/private/insert-order', json=data) as response:
        status = response.status
        print(f'Received status {status}')
        text = await response.text()
        print(f'Received text: {text}')
        return text

async def main():
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(f'ws://{host}:1957/private/ws') as ws:
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

            client_order_id = int(time.time()*1e9)
            done, pending = await asyncio.wait([insert(session, client_order_id, 5e9),
                                                insert(session, client_order_id+1, 5e3)])
            results = [task.result() for task in done]
            print(results)

            print('Test DONE')


asyncio.run(main())
