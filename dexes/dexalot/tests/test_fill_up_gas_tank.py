import aiohttp
import asyncio


async def main():
    async with aiohttp.ClientSession() as session:
        data = {'amount': '1', 'timeout': 10}
        async with session.post('http://localhost:1957/private/fill-up-gas-tank', json=data) as response:
            status = response.status
            print(f'Received status {status}')

            text = await response.text()
            print(f'Received text: {text}')

            print('Test DONE')


asyncio.run(main())
