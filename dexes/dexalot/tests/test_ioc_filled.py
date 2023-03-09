import aiohttp
import asyncio
import time

host = 'dev-vrg-trade0.kdev:21443'

async def insert(session):
    data = {
        'client_order_id': str(int(time.time()*1e9)),
        'symbol': 'ALOT/USDC',
        'price': '5.1',
        'qty': '5',
        'side': 'SELL',
        'type1': 1,
        'type2': 2,
        'gas_price_wei': 6e9,
        'timeout': 10
    }

    async with session.post(f'https://{host}/private/insert-order', json=data) as response:
        status = response.status
        print(f'Received status {status}')
        text = await response.text()
        print(f'Received text: {text}')

async def main():
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(verify_ssl=False)) as session:
        async with session.ws_connect(f'wss://{host}/private/ws') as ws:
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

            sub = {
                'id': 2,
                'jsonrpc': '2.0',
                'method': 'subscribe',
                'params': {'channel': 'TRADE'}
            }
            print('Subscription request: ', sub)
            await ws.send_json(sub)
            sub_reply = await ws.receive_json()
            print('Subscription reply: ', sub_reply)

            await insert(session)

            trade = await ws.receive_json()
            print('TRADE: ', trade)

            osf = await ws.receive_json()
            print('OSF: ', osf)

            print('Test DONE')


asyncio.get_event_loop().run_until_complete(main())
