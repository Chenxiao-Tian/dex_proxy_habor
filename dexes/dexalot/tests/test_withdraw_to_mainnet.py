import aiohttp
import asyncio

async def withdraw(session, symbol, amount):
    data = {'symbol': symbol, 'amount': str(amount), 'timeout': 10}
    async with session.post('http://localhost:1957/private/withdraw', json=data) as response:
        status = response.status
        print(f'Received status {status}')
        text = await response.text()
        print(f'Received text: {text}')

async def main():
    async with aiohttp.ClientSession() as session:
        print('Withdrawing token AVAX...')
        await withdraw(session, 'AVAX', 1)

        #print('Withdrawing native ALOT...')
        #await withdraw(session, 'ALOT', 1)

        print('Test DONE')


asyncio.run(main())
