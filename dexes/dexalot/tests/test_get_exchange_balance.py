import aiohttp
import asyncio

async def get_balance(session, symbol):
    async with session.get(f'http://localhost:1957/public/get-exchange-balance?symbol={symbol}') as response:
        status = response.status
        print(f'Received status {status}')
        text = await response.text()
        print(f'Received text: {text}')

async def main():
    async with aiohttp.ClientSession() as session:
        print('Getting ALOT exchange balance...')
        await get_balance(session, 'ALOT')

        print('Getting AVAX exchange balance...')
        await get_balance(session, 'AVAX')

        print('Test DONE')


asyncio.run(main())
