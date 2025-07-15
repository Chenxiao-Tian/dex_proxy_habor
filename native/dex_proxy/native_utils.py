from eth_account import Account
from web3 import Web3


def sign_quote(eth_private_key, pool_address, quote_data):
    try:
        signatureData = {
            "types": {
                "Order": [
                    {"name": "id", "type": "uint256"},
                    {"name": "signer", "type": "address"},
                    {"name": "buyer", "type": "address"},
                    {"name": "seller", "type": "address"},
                    {"name": "buyerToken", "type": "address"},
                    {"name": "sellerToken", "type": "address"},
                    {"name": "buyerTokenAmount", "type": "uint256"},
                    {"name": "sellerTokenAmount", "type": "uint256"},
                    {"name": "deadlineTimestamp", "type": "uint256"},
                    {"name": "caller", "type": "address"},
                    {"name": "quoteId", "type": "bytes16"}
                ]
            },
            "primaryType": "Order",
            "domain": {
                "name": "native pool",
                "version": "1",
                "chainId": quote_data['chainId'],
                "verifyingContract": pool_address
            },
            "message": {
                "id": quote_data["id"],
                "signer": quote_data["signer"],
                "buyer": quote_data["buyer"],
                "seller": quote_data["seller"],
                "buyerToken": quote_data["buyerToken"],
                "sellerToken": quote_data["sellerToken"],
                "buyerTokenAmount": quote_data["buyerTokenAmount"],
                "sellerTokenAmount": quote_data["sellerTokenAmount"],
                "deadlineTimestamp": quote_data["deadlineTimestamp"],
                "caller": quote_data["caller"],
                "quoteId": Web3.to_bytes(hexstr=quote_data["quoteId"].replace('-', ''))
            }
        }

        signed_typed_data = Account.sign_typed_data(
            eth_private_key,
            signatureData["domain"],
            signatureData["types"],
            signatureData["message"]
        )

        return signed_typed_data.signature.hex()
    except Exception as exc:
        # Making sure we don't include any private key details
        raise Exception(f'Error signing bid')
