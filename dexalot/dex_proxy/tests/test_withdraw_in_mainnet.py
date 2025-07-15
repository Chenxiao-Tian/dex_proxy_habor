import aiohttp
import asyncio
import time

host = 'dev-sng-build1.kdev'


async def withdraw(session, symbol, amount):
    data = {
        'client_request_id': str(int(time.time() * 1e9)),
        'symbol': symbol,
        'amount': str(amount),
        # good address
        'address_to': '0x03CdE1E0bc6C1e096505253b310Cf454b0b462FB',
        # bad address
        # 'address_to': '0x03CdE1E0bc6C1e096505253b310Cf454b0b462FC',
        'gas_limit': 5e5,
        'gas_price_wei': 25e9
    }
    async with session.post(f'http://{host}:1957/private/withdraw', json=data) as response:
        status = response.status
        print(f'Received status {status}')
        text = await response.text()
        print(f'Received text: {text}')


async def main():
    async with aiohttp.ClientSession() as session:
        print('Withdrawing 100 USDC...')
        await withdraw(session, 'USDC', 100)

        print('Withdrawing 5 ALOT...')
        await withdraw(session, 'ALOT', 5)

        print('Test DONE')


asyncio.run(main())
