import aiohttp
import asyncio


async def main():
    async with aiohttp.ClientSession() as session:
        async with session.get('http://dev-sng-both0.kdev:1957/public/get-order?order_id=0x0000000000000000000000000000000000000000000000000000000063178d03') as response:
            status = response.status
            print(f'Received status {status}')

            text = await response.text()
            print(f'Received text: {text}')

            print('Test DONE')


asyncio.run(main())
