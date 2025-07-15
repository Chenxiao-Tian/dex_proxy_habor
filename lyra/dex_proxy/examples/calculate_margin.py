from web3.auto import w3
from eth_account.messages import encode_defunct
import time
import requests
import ujson
import pprint

# private key for the ES test wallet
eth_private_key = 'e81e556a84ffe1a2ca012ecd639e221e27321ee5aeaafc312c056aaf44f280c5'

# Initialize Ethereum account
w3.eth.account.enable_unaudited_hdwallet_features()
eth_account = w3.eth.account.from_key(eth_private_key)
eth_account_address, eth_account_private_key_hex = (
    eth_account.address,
    eth_account.key.hex(),
)

# Generate signature
ts = str(int(time.time() * 1000))
msg = encode_defunct(text=ts)
signed = w3.eth.account.sign_message(msg, eth_private_key)
signature = signed.signature.hex()

url = "https://api-demo.lyra.finance/private/get_margin"

payload = {
    "subaccount_id": 1281,
    "simulated_position_changes": [
        {
            "amount": "0.1",
            "entry_price": "37000",
            "instrument_name": "BTC-PERP"
        }
    ]
}
headers = {
    "accept": "application/json",
    "content-type": "application/json",
    "X-LyraWallet": eth_account_address.lower(),
    "X-LyraTimestamp": ts,
    "X-LyraSignature": signature
}

print("payload")
print(ujson.dumps(payload, indent=4))
print('-' * 80)

print("response")
response = requests.post(url, json=payload, headers=headers)
print(ujson.dumps(ujson.loads(response.text), indent=4))
print('-' * 80)
