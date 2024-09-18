import aiohttp
import asyncio

from web3 import Web3

host = 'localhost'


async def sign_order(session, amount):
    data = {
        "quote_data":
        {
            "id": 0,
            "signer": '0x9e2505ff3565d7c83a9cbcfd260c4a545780b402',
            "buyer": "0xaaE854bdd940cf402d79e8051DC7E3390e32A3ac",
            "seller": "0x0144cc36072Bad3880Ff1b40b1369BFfeC3f3839",
            "buyerToken": '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2',
            "sellerToken": '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48',
            "buyerTokenAmount":  "10100000000000000000000",
            "sellerTokenAmount": "10000000000000000000000",
            "deadlineTimestamp": "1671086729",
            "chainId": 56,
            "txOrigin": "0x7d1F5C43998570629f5d00134321fB6a95451ec3",
            "caller": '0x0144cc36072Bad3880Ff1b40b1369BFfeC3f3839',
            "auth": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
            "quoteId": '62716-206e-41cb-8559-013f1ed1a65a'
        }
    }

    async with session.post(f'http://{host}:1958/private/order-signature', json=data) as response:
        status = response.status
        print(f'Received status {status}')
        text = await response.text()
        print(f'Received text: {text}')


async def main():
    async with aiohttp.ClientSession() as session:
        print('Getting order signature...')
        await sign_order(session, 10)

        print('Test DONE')


asyncio.get_event_loop().run_until_complete(main())
