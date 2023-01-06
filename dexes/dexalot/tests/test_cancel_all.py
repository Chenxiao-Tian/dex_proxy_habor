import aiohttp
import asyncio


async def main():
    async with aiohttp.ClientSession() as session:
        async with session.delete('http://dev-sng-both0.kdev:1957/private/cancel-all') as response:
            status = response.status
            print(f'Received status {status}')

            text = await response.text()
            print(f'Received text: {text}')

            print('Test DONE')


asyncio.run(main())
