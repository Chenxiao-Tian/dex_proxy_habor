from web3.auto import w3
from web3 import Web3, HTTPProvider
import py_eth_sig_utils
from eth_account.messages import encode_defunct
from eth_abi import encode
import time
import os
import requests
import ujson
import pprint
import random

from web3.middleware import construct_sign_and_send_raw_middleware, geth_poa_middleware


# private key for the ES test wallet
eth_private_key = 0xe81e556a84ffe1a2ca012ecd639e221e27321ee5aeaafc312c056aaf44f280c5

# eth_account_address = '0x03CdE1E0bc6C1e096505253b310Cf454b0b462FB'


# Initialize Ethereum account
w3.eth.account.enable_unaudited_hdwallet_features()
eth_account = w3.eth.account.from_key(eth_private_key)
eth_account_address, eth_account_private_key_hex = (
    eth_account.address,
    eth_account.key.hex(),
)

print("eth_account_address: {}".format(eth_account_address))

DEPOSIT_MODULE_ADDRESS = '0x43223Db33AdA0575D2E100829543f8B04A37a1ec'
ACTION_TYPEHASH = '0x4d7a9f27c403ff9c0f19bce61d76d82f9aa29f8d6d4b0c5474607d9770d1af17'
DOMAIN_SEPARATOR = '0x9bcf4dc06df5d8bf23af818d5716491b995020f377d3b7b64c29ed14e3dd1105'

CASH_ADDRESS = '0x6caf294DaC985ff653d5aE75b4FF8E0A66025928'
USDC_ADDRESS = '0xe80F2a02398BBf1ab2C9cc52caD1978159c215BD'

#standard
#RISK_MANAGER_ADDRESS = '0x28bE681F7bEa6f465cbcA1D25A2125fe7533391C'
#btc pm
RISK_MANAGER_ADDRESS = '0xbaC0328cd4Af53d52F9266Cdbd5bf46720320A20'
#eth pm
#RISK_MANAGER_ADDRESS = '0xDF448056d7bf3f9Ca13d713114e17f1B7470DeBF'

amount = "10000"
subaccount_id = 1281


outputs = {}

def approve_contract(amount):
    contract_abi = '''
    [{
    "constant": false,
    "inputs": [
      {
        "name": "spender",
        "type": "address"
      },
      {
        "name": "value",
        "type": "uint256"
      }
    ],
    "name": "approve",
    "outputs": [
      {
        "name": "",
        "type": "bool"
      }
    ],
    "payable": false,
    "stateMutability": "nonpayable",
    "type": "function"
  }]
  '''

    web3_provider = "https://l2-prod-testnet-0eakp60405.t.conduit.xyz"

    w3_p = Web3(HTTPProvider(web3_provider))

    w3_p.middleware_onion.add(
                construct_sign_and_send_raw_middleware(eth_account))

    w3_p.eth.default_account = eth_account

    print("got provider")

    contract = w3_p.eth.contract(address=USDC_ADDRESS, abi=contract_abi)

    #success = contract.functions.approve(DEPOSIT_MODULE_ADDRESS, int(amount) * int(1e18)).call()

    transaction = contract.functions.approve(DEPOSIT_MODULE_ADDRESS, int(amount) * int(1e6)).build_transaction({'from': eth_account_address,'gasPrice': w3.to_wei('5', 'gwei'),'nonce': w3_p.eth.get_transaction_count(eth_account_address),'gas': 100000,})

    signed_txn = w3_p.eth.account.sign_transaction(transaction, private_key=eth_private_key)
    tx_token = w3_p.eth.send_raw_transaction(signed_txn.rawTransaction)
    tx_hash = w3.to_hex(tx_token)
    print("Transaction Hash: ",str(tx_hash))
    response = w3_p.eth.wait_for_transaction_receipt(tx_hash)

    print("response approved: {}".format(response))


def encode_deposit_data(amount):
    encoded_data = encode(["uint256", "address", "address"],
                          [
                              # likely only works for usdc
                              int(amount) * int(1e6), #w3.to_wei(amount, "ether"),
                              CASH_ADDRESS,
                              RISK_MANAGER_ADDRESS
                          ])

    outputs["encoded_data"] = w3.to_hex(encoded_data)

    return encoded_data


def generate_signature(subaccount_id, encoded_data_hashed, sig_expiry, nonce,
                       wallet_address):

    action_hash = w3.keccak(hexstr=w3.to_hex(encode(
        [
            "bytes32",
            "uint256",
            "uint256",
            "address",
            "bytes32",
            "uint256",
            "address",
            "address"
        ],
        [
            w3.to_bytes(hexstr=ACTION_TYPEHASH),
            subaccount_id,
            nonce,
            DEPOSIT_MODULE_ADDRESS,
            encoded_data_hashed,
            sig_expiry,
            wallet_address,
            wallet_address
        ]
    )))

    outputs["action_hash"] = w3.to_hex(action_hash)

    buffer = w3.to_bytes(hexstr="1901") + w3.to_bytes(hexstr=DOMAIN_SEPARATOR) + action_hash
    typed_data_hash = w3.keccak(buffer)

    outputs["typed_data_hash"] = w3.to_hex(typed_data_hash)

    v,r,s = py_eth_sig_utils.utils.ecsign(w3.to_bytes(typed_data_hash), w3.to_bytes(eth_private_key))
    d =  w3.to_hex(w3.to_bytes(r) + w3.to_bytes(s) + w3.to_bytes(v))

    print(d)
    return d


url = "https://api-demo.lyra.finance/private/deposit"

start = time.time()

now_ms = int(time.time() * 1000)
random_suffix = int(random.random() * 999)
nonce = int(f"{now_ms}{random_suffix}")

approve_contract(amount)

print("now sign request")

encoded_deposit_data = encode_deposit_data(amount)
encoded_data_hashed = w3.keccak(hexstr=w3.to_hex(encoded_deposit_data)[2:])
outputs["encoded_data_hashed"] = w3.to_hex(encoded_data_hashed)
deposit_signature_expiry = int(now_ms / 1000) + 700
deposit_signature = generate_signature(subaccount_id,
                                       encoded_data_hashed,
                                       deposit_signature_expiry, nonce,
                                       eth_account_address)

end = time.time()

print("sign took {}".format(end - start))
payload = {
    "amount": amount,
    "asset_name": "USDC",
    "nonce": nonce,
    "subaccount_id": subaccount_id,
    "signature": deposit_signature,
    "signature_expiry_sec": deposit_signature_expiry,
    "signer": eth_account_address
}

# Generate signature for header
msg = encode_defunct(text=str(now_ms))
signed_msg = w3.eth.account.sign_message(msg, eth_private_key)
signature = signed_msg.signature.hex()

headers = {
    "accept": "application/json",
    "content-type": "application/json",
    "X-LyraWallet": eth_account_address,
    "X-LyraTimestamp": str(now_ms),
    "X-LyraSignature": signature
}

pprint.pprint(payload)
pprint.pprint(headers)

response = requests.post(url, json=payload, headers=headers).text
print(response)

response = ujson.loads(response)


