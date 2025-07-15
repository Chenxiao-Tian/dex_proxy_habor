from websocket import create_connection

from web3.auto import w3
import py_eth_sig_utils
from eth_account.messages import encode_defunct
from eth_abi import encode
import time
import os
import requests
import ujson
import pprint
import random

# private key for the ES test wallet
eth_private_key = 0xe81e556a84ffe1a2ca012ecd639e221e27321ee5aeaafc312c056aaf44f280c5

# Initialize Ethereum account
w3.eth.account.enable_unaudited_hdwallet_features()
eth_account = w3.eth.account.from_key(eth_private_key)
eth_account_address, eth_account_private_key_hex = (
    eth_account.address,
    eth_account.key.hex(),
)


CASH_ADDRESS = "0xb8a082B53BdCBFB7c44C8Baf2F924096711EADcA"
STANDARD_RISK_MANAGER_ADDRESS = "0x089fde8A32CD4Ef8D9F69DAed1B4CD5aC67d1ed7"
DEPOSIT_MODULE_ADDRESS = "0xB430F3AE49f9d7a9B93fCCb558424972c385Cc38"
ACTION_TYPEHASH = "0x4d7a9f27c403ff9c0f19bce61d76d82f9aa29f8d6d4b0c5474607d9770d1af17"

# generated from some info about the contracts / exchange
# https://eips.ethereum.org/EIPS/eip-712
DOMAIN_SEPARATOR = "0xff2ba7c8d1c63329d3c2c6c9c19113440c004c51fe6413f65654962afaff00f3"

OPTION_NAME = 'ETH-20231027-1500-P'
ASSET_ADDRESS = '0x8932cc48F7AD0c6c7974606cFD7bCeE2F543a124'
OPTION_SUB_ID = 644245094401698393600
TRADE_MODULE_ADDRESS = '0x63Bc9D10f088eddc39A6c40Ff81E99516dfD5269'

def encode_order_data(order):
    encoded_data = encode(
        ['address', 'uint', 'int', 'int', 'uint', 'uint', 'bool'],
        [
            ASSET_ADDRESS,
            OPTION_SUB_ID,
            # likely only works for eth
            int(float(order['limit_price']) * int(1e18)),
            int(float(order['amount']) * int(1e18)),
            int(float(order['max_fee']) * int(1e18)),
            order['subaccount_id'],
            order['direction'] == 'buy'
        ])

    return encoded_data


def generate_signature(order, encoded_data_hashed):
    action_hash = w3.keccak(hexstr=w3.to_hex(encode(
          ['bytes32', 'uint256', 'uint256', 'address', 'bytes32', 'uint256', 'address', 'address'],
        [
            w3.to_bytes(hexstr=ACTION_TYPEHASH),
            order['subaccount_id'],
            order['nonce'],
            TRADE_MODULE_ADDRESS,
            encoded_data_hashed,
            order['signature_expiry_sec'],
            order['signer'], # wallet
            order['signer']
        ]
    )))

    buffer = w3.to_bytes(hexstr="1901") + w3.to_bytes(hexstr=DOMAIN_SEPARATOR) + action_hash
    typed_data_hash = w3.keccak(buffer)

    v,r,s = py_eth_sig_utils.utils.ecsign(w3.to_bytes(typed_data_hash), w3.to_bytes(eth_private_key))
    d =  w3.to_hex(w3.to_bytes(r) + w3.to_bytes(s) + w3.to_bytes(v))

    return d


url = "https://api-demo.lyra.finance/private/order"

subaccount_id = 132

start = time.time()

now_ms = int(time.time() * 1000)
random_suffix = int(random.random() * 999)
nonce = int(f"{now_ms}{random_suffix}")

def define_order():
    return {
        'instrument_name': OPTION_NAME,
        'subaccount_id': subaccount_id,
        'direction': "buy",
        'limit_price': 310,
        'amount': 1,
        'signature_expiry_sec': int(time.time()) + 300,
        'max_fee': "0.01",
        'nonce': nonce,
        'signer': eth_account_address,
        'order_type': "limit",
        'mmp': False,
        'signature': "filled_in_below"
    }

order = define_order()

encoded_data = encode_order_data(order)
encoded_data_hashed = w3.keccak(hexstr=w3.to_hex(encoded_data)[2:])
signature_expiry = int(now_ms / 1000) + 300
signature = generate_signature(order, encoded_data_hashed)

order['signature'] = signature

end = time.time()

print("sign took {}".format(end - start))

ws = create_connection("wss://api-demo.lyra.finance/ws")

# Generate signature
ts = str(int(time.time() * 1000))
msg = encode_defunct(text=ts)
signed = w3.eth.account.sign_message(msg, eth_private_key)
signature = signed.signature.hex()

logon_msg = {
        'method': 'public/login',
        'params': {
      'wallet': eth_account_address,
      'timestamp': ts,
      'signature': signature
            },
        'id': int(random.random() * 10000)
    }

print(logon_msg)
ws.send(ujson.dumps(logon_msg))

result = ws.recv()
print("Received: ", result)

order_msg = {
            'method': 'private/order',
            'params': order,
        'id': int(random.random() * 10000)
        }

print(order_msg)
ws.send(ujson.dumps(order_msg))


while (True):
    print("final Receiving...")
    result = ws.recv()
    print("Received: ", result)

