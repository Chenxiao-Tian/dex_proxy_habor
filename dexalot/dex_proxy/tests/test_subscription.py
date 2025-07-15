import aiohttp
import asyncio


host = 'dev-sng-build1.kdev'

async def main():
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(f'ws://{host}:1957/private/ws') as ws:
            sub = {
                'id': 1,
                'jsonrpc': '2.0',
                'method': 'subscribe',
                'params': {'channel': 'ORDER'}
            }
            print('Sending subscribe request: ', sub)
            await ws.send_json(sub)
            sub_reply = await ws.receive_json()
            print('Received subscribe reply: ', sub_reply)

            dup_sub = {
                'id': 2,
                'jsonrpc': '2.0',
                'method': 'subscribe',
                'params': {'channel': 'ORDER'}
            }
            print('Sending subscribe request: ', dup_sub)
            await ws.send_json(dup_sub)
            sub_reply = await ws.receive_json()
            print('Received subscribe reply: ', sub_reply)

            unsub = {
                'id': 3,
                'jsonrpc': '2.0',
                'method': 'unsubscribe',
                'params': {'channel': 'ORDER'}
            }
            print('Sending unsubscribe request: ', unsub)
            await ws.send_json(unsub)
            unsub_reply = await ws.receive_json()
            print('Received unsubscribe reply: ', unsub_reply)

            dup_unsub = {
                'id': 4,
                'jsonrpc': '2.0',
                'method': 'unsubscribe',
                'params': {'channel': 'ORDER'}
            }
            print('Sending unsubscribe request: ', dup_unsub)
            await ws.send_json(dup_unsub)
            unsub_reply = await ws.receive_json()
            print('Received unsubscribe reply: ', unsub_reply)

            unknown_sub = {
                'id': 5,
                'jsonrpc': '2.0',
                'method': 'subscribe',
                'params': {'channel': 'UNKNOWN_CHANNEL'}
            }
            print('Sending subscribe request: ', unknown_sub)
            await ws.send_json(unknown_sub)
            sub_reply = await ws.receive_json()
            print('Received subscribe reply: ', sub_reply)

            print('Test DONE')


asyncio.run(main())
