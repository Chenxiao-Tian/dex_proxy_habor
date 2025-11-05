import aiohttp
import asyncio
import time

host = 'localhost'

async def get_open_requests(session, type: str):
    async with session.get(f'http://{host}:1958/public/get-all-open-requests?request_type={type}') as response:
        status = response.status
        print(f'Received status {status}')
        text = await response.text()
        print(f'Received text: {text}')    

async def get_request(session, client_request_id: str):
    async with session.get(f'http://{host}:1958/public/get-request-status?client_request_id={client_request_id}') as response:
        status = response.status
        print(f'Received status {status}')
        text = await response.text()
        print(f'Received text: {text}')   
        
async def approve(session, amount):
    data = {
        'client_request_id': str(int(time.time() * 1e9)),
        'symbol': 'USDC',
        'amount': str(amount),
        'gas_price_wei': 25e9
    }
    async with session.post(f'http://{host}:1958/private/approve-token', json=data) as response:
        status = response.status
        print(f'Received status {status}')
        text = await response.text()
        print(f'Received text: {text}')

async def deposit(session, amount):
    data = {
        'client_request_id': str(int(time.time() * 1e9)),
        'symbol': 'USDC',
        'amount': str(amount),
        'gas_limit': 5e5,
        'gas_price_wei': 25e9
    }

    async with session.post(f'http://{host}:1958/private/deposit-into-exchange', json=data) as response:
        status = response.status
        print(f'Received status {status}')
        text = await response.text()
        print(f'Received text: {text}')
        
async def withdraw(session, amount):
    data = {
        'client_request_id': str(int(time.time() * 1e9)),
        'symbol': 'USDC',
        'amount': str(amount)
    }
    async with session.post(f'http://{host}:1958/private/withdraw-from-exchange', json=data) as response:
        status = response.status
        print(f'Received status {status}')
        text = await response.text()
        print(f'Received text: {text}')


async def main():
    async with aiohttp.ClientSession() as session:
        await get_open_requests(session, 'TRANSFER')
        await get_open_requests(session, 'ORDER')
        await get_request(session, '123')
        await approve(session, 1.5)
        #await deposit(session, 1.5)
        #await withdraw(session, 1.5)
        print('Test DONE')


asyncio.get_event_loop().run_until_complete(main())
