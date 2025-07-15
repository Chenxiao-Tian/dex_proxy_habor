import aiohttp
import asyncio

host = 'dev-sng-build1.kdev'

async def main():
    async with aiohttp.ClientSession() as session:
        async with session.delete(f'http://{host}:1957/private/cancel-all-orders?timeout=10') as response:
            status = response.status
            print(f'Received status {status}')

            text = await response.text()
            print(f'Received text: {text}')

            print('Test DONE')


asyncio.run(main())
