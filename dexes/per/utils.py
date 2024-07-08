import web3

from eth_account import Account
from eth_utils import to_checksum_address

from typing import Union, cast


def _get_permitted_tokens(
        sell_tokens: list[dict],
        bid_amount: int,
        call_value: int,
        weth_address: str,
) -> list[dict[str, Union[str, int]]]:
    """
    Extracts the sell tokens in the permit format.

    Args:
        sell_tokens: A list of TokenAmount objects representing the sell tokens.
        bid_amount: An integer representing the amount of the bid (in wei).
        call_value: An integer representing the call value of the bid (in wei).
        weth_address: The address of the WETH token.
    Returns:
        A list of dictionaries representing the sell tokens in the permit format.
    """
    permitted_tokens: list[dict[str, Union[str, int]]] = [
        {
            "token": token['token'],
            "amount": int(token['amount']),
        }
        for token in sell_tokens
    ]

    for token in permitted_tokens:
        if token["token"] == weth_address:
            sell_token_amount = cast(int, token["amount"])
            token["amount"] = sell_token_amount + call_value + bid_amount
            return permitted_tokens

    if bid_amount + call_value > 0:
        permitted_tokens.append(
            {
                "token": weth_address,
                "amount": bid_amount + call_value,
            }
        )

    return permitted_tokens


def compute_create2_address(
        searcher_address: str,
        opportunity_adapter_factory_address: str,
        opportunity_adapter_init_bytecode_hash: str,
) -> str:
    """
    Computes the CREATE2 address for the opportunity adapter belonging to the searcher.

    Args:
        searcher_address: The address of the searcher's wallet.
        opportunity_adapter_factory_address: The address of the opportunity adapter factory.
        opportunity_adapter_init_bytecode_hash: The hash of the init code for the opportunity adapter.
    Returns:
        The computed CREATE2 address for the opportunity adapter.
    """
    pre = b"\xff"
    opportunity_adapter_factory = bytes.fromhex(
        opportunity_adapter_factory_address.replace("0x", "")
    )
    wallet = bytes.fromhex(searcher_address.replace("0x", ""))
    salt = bytes(12) + wallet
    init_code_hash = bytes.fromhex(
        opportunity_adapter_init_bytecode_hash.replace("0x", "")
    )
    result = web3.Web3.keccak(pre + opportunity_adapter_factory + salt + init_code_hash)
    return to_checksum_address(result[12:].hex())


def sign_bid(eth_private_key: str, opportunity: dict, opportunity_adapter: dict, bid_params: dict) -> str:
    try:
        domain_data = {
            "name": "Permit2",
            "chainId": opportunity_adapter['chain_id'],
            "verifyingContract": opportunity_adapter['permit2'],
        }

        message_types = {
            "PermitBatchWitnessTransferFrom": [
                {"name": "permitted", "type": "TokenPermissions[]"},
                {"name": "spender", "type": "address"},
                {"name": "nonce", "type": "uint256"},
                {"name": "deadline", "type": "uint256"},
                {"name": "witness", "type": "OpportunityWitness"},
            ],
            "OpportunityWitness": [
                {"name": "buyTokens", "type": "TokenAmount[]"},
                {"name": "executor", "type": "address"},
                {"name": "targetContract", "type": "address"},
                {"name": "targetCalldata", "type": "bytes"},
                {"name": "targetCallValue", "type": "uint256"},
                {"name": "bidAmount", "type": "uint256"},
            ],
            "TokenAmount": [
                {"name": "token", "type": "address"},
                {"name": "amount", "type": "uint256"},
            ],
            "TokenPermissions": [
                {"name": "token", "type": "address"},
                {"name": "amount", "type": "uint256"},
            ]
        }

        executor = Account.from_key(eth_private_key).address

        message_data = {
            "permitted": _get_permitted_tokens(
                opportunity['sell_tokens'],
                int(bid_params['amount']),
                int(opportunity['target_call_value']),
                opportunity_adapter['weth'],
            ),
            "spender": compute_create2_address(
                executor,
                opportunity_adapter['opportunity_adapter_factory'],
                opportunity_adapter['opportunity_adapter_init_bytecode_hash'],
            ),
            "nonce": int(bid_params['nonce']),
            "deadline": int(bid_params['deadline']),
            "witness": {
                "buyTokens": [
                    {
                        "token": token['token'],
                        "amount": int(token['amount']),
                    }
                    for token in opportunity['buy_tokens']
                ],
                "executor": executor,
                "targetContract": opportunity['target_contract'],
                "targetCalldata": bytes.fromhex(
                    opportunity['target_calldata'].replace("0x", "")
                ),
                "targetCallValue": opportunity['target_call_value'],
                "bidAmount": int(bid_params['amount']),
            },
        }

        signed_typed_data = Account.sign_typed_data(
            eth_private_key, domain_data, message_types, message_data
        )

        return signed_typed_data.signature.hex()
    except Exception:
        # Making sure we don't include any private key details
        raise Exception(f'Error signing bid')
