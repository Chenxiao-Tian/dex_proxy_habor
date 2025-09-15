import aiohttp
import asyncio
import time

host = 'localhost'


async def withdraw(session, amount):
    data = {
        'client_request_id': str(int(time.time() * 1e9)),
        'token': 'UBTC',
        'amount': str(amount),
        'destination': '19VLauSfjKX7kbUuBENWBfufxJybEoiG83'
    }
    async with session.post(f'http://{host}:1958/private/send-spot-token', json=data) as response:
        status = response.status
        print(f'Received status {status}')
        text = await response.text()
        print(f'Received text: {text}')


async def main():
    async with aiohttp.ClientSession() as session:
        print('withdraw $1.5...')
        await withdraw(session, 1.5)
        print('Test DONE')


asyncio.get_event_loop().run_until_complete(main())
