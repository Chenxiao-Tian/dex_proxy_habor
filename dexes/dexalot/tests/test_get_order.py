import aiohttp
import asyncio
import time

host = 'dev-sng-build1.kdev'


async def insert(session):
    client_oid = str(int(time.time() * 1e9))
    data = {
        'client_order_id': client_oid,
        'symbol': 'ALOT/USDC',
        'price': '10',
        'qty': '4',
        'side': 'SELL',
        'type1': 1,
        'type2': 0,
        'gas_price_wei': 5e9,
        'timeout': 10
    }

    async with session.post(f'http://{host}:1957/private/insert-order', json=data) as response:
        status = response.status
        print(f'Received status {status}')
        text = await response.text()
        print(f'Received text: {text}')

    return client_oid


async def query(session, order_id, client_oid):
    if order_id:
        path = f'http://{host}:1957/public/get-order?order_id={order_id}'
    else:
        path = f'http://{host}:1957/public/get-order?client_order_id={client_oid}'

    async with session.get(path) as response:
        status = response.status
        print(f'Received status {status}')
        text = await response.text()
        print(f'Received text: {text}')


async def cancel(session, order_id):
    async with session.delete(f'http://{host}:1957/private/cancel-order?order_id={order_id}&timeout=10') as response:
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

            client_oid = await insert(session)

            await query(session, None, client_oid)

            osf = await ws.receive_json()
            print('OSF: ', osf)

            order_id = osf['params']['data']['oid']
            await query(session, order_id, client_oid)

            await cancel(session, order_id)

            osf = await ws.receive_json()
            print('OSF: ', osf)

            print('Test DONE')


asyncio.run(main())
