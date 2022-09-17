import aiohttp
import asyncio
import time

async def main():
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect('ws://localhost:8081/private/ws') as ws:
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

            insert = {
                'id': 2,
                'jsonrpc': '2.0',
                'method': 'insert_order',
                'params': {
                    'client_order_id': str(time.time_ns()),
                    'symbol': 'ALOT/AVAX',
                    'price': '0.15',
                    'qty': '3',
                    'side': 'BUY',
                    'type1': 1,
                    'type2': 3,
                    'timeout': 10}}
            print('Insert request ', insert)
            await ws.send_json(insert)
            insert_reply = await ws.receive_json()
            print('Insert reply: ', insert_reply)

            print('Test DONE')


asyncio.run(main())
