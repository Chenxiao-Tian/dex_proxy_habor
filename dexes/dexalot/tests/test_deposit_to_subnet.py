import aiohttp
import asyncio

async def deposit(session, symbol, amount):
    data = {'symbol': symbol, 'amount': str(amount), 'timeout': 10}
    async with session.post('http://localhost:1957/private/deposit', json=data) as response:
        status = response.status
        print(f'Received status {status}')
        text = await response.text()
        print(f'Received text: {text}')

async def main():
    async with aiohttp.ClientSession() as session:
        print('Depositing token ALOT...')
        await deposit(session, 'ALOT', 2)

        #print('Depositing native AVAX...')
        #await deposit(session, 'AVAX', 2)

        print('Test DONE')


asyncio.run(main())
