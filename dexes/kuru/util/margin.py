import logging
import math

from eth_typing import HexStr
from eth_utils.currency import to_wei, from_wei
from kuru_sdk import MarginAccount
from web3 import Web3, HTTPProvider

log = logging.getLogger(__name__)

async def add_margin_balance(url: str, price: str, size: str, num_orders: int, private_key: str):
    web3 = Web3(HTTPProvider(url))
    margin_contract_addr = "0x4B186949F31FCA0aD08497Df9169a6bEbF0e26ef"
    
    margin_account = MarginAccount(
        web3=web3, contract_address=margin_contract_addr, private_key=private_key
    )

    size_mon = float(price) * float(size) * num_orders  # make deposit for num_orders orders
    size_wei = to_wei(size_mon, "ether")
    size_wei = 10 * math.ceil(float(size_wei) / 10)

    print(f"Try margin deposit: Contract: {margin_account.contract_address}, Size: {size_mon} {margin_account.NATIVE}, Wei: {size_wei}; Private: {margin_account.private_key[:8]}...{margin_account.private_key[-8:]}")

    margin_account_deposit_tx_hash = await margin_account.deposit(margin_account.NATIVE, size_wei)
    log.info(f"Deposit transaction hash: {margin_account_deposit_tx_hash}")

    assert margin_account_deposit_tx_hash is not None
    assert len(margin_account_deposit_tx_hash) > 0

    # Wait for the deposit transaction to be confirmed
    tx_receipt = web3.eth.wait_for_transaction_receipt(HexStr(margin_account_deposit_tx_hash))
    assert tx_receipt["status"] == 1, "Margin deposit transaction failed"
    log.info(f"Margin deposit transaction confirmed, block_number: {tx_receipt['blockNumber']}")


async def clear_margin_balance(url: str, private_key: str):
    web3 = Web3(HTTPProvider(url))
    margin_contract_addr = "0x4B186949F31FCA0aD08497Df9169a6bEbF0e26ef"
    
    margin_account = MarginAccount(
        web3=web3, contract_address=margin_contract_addr, private_key=private_key
    )

    # Get current balance
    balance = await margin_account.get_balance(str(margin_account.wallet_address), margin_account.NATIVE)
    log.info(f"Clearing margin account balance: {from_wei(balance, 'ether')} MON")
    
    if balance > 0:
        tx_hash = await margin_account.withdraw(margin_account.NATIVE, balance)
        log.info(f"Withdraw transaction hash: {tx_hash}")
        assert tx_hash is not None
        assert len(tx_hash) > 0

        receipt = web3.eth.wait_for_transaction_receipt(HexStr(tx_hash))
        assert receipt["status"] == 1, f"Margin deposit clear transaction failed {receipt}"

        balance = await margin_account.get_balance(str(margin_account.wallet_address), margin_account.NATIVE)
        log.info(f"New margin account balance: {from_wei(balance, 'ether')} MON")
        assert balance == 0

async def get_margin_balance(url: str, private_key: str, token: str):
    web3 = Web3(HTTPProvider(url))
    margin_contract_addr = "0x4B186949F31FCA0aD08497Df9169a6bEbF0e26ef"

    margin_account = MarginAccount(
        web3=web3, contract_address=margin_contract_addr, private_key=private_key
    )

    # Get current balance
    balance = await margin_account.get_balance(str(margin_account.wallet_address), token)
    log.info(f"Margin account balance: {from_wei(balance, 'ether')} for token {token}")

    return balance
