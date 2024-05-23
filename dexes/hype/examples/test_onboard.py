import aiohttp
import asyncio
import time

_host = 'http://dev-sng-both1.kdev:11968'
host = 'http://localhost:1958'


async def onboard(session):
    # Step 1: Deposit into the exchange
    data = {
        'client_request_id': str(int(time.time() * 1e9)),
        'symbol': 'USDC',
        'amount': str(1.9),
        'gas_limit': 5e5,
        'gas_price_wei': 25e9
    }

    async with session.post(f'{host}/private/deposit-into-exchange', json=data) as r1:
        status = r1.status
        print(f'Received status {status}')
        text = await r1.text()
        print(f'Received text: {text}')

    time.sleep(30)

    # Step 2: Approve agent
    data = {
    }

    async with session.post(f'{host}/private/approve-agent', json=data) as r2:
        status = r2.status
        print(f'Received status {status}')
        text = await r2.text()
        print(f'Received text: {text}')


async def main():
    async with aiohttp.ClientSession() as session:
        await onboard(session)
        print('Test DONE')


asyncio.get_event_loop().run_until_complete(main())
