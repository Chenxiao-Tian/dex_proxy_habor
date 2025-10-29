"""Minimal stub of eth_account.Account."""


class Account:
    @staticmethod
    def decrypt(encrypted_key: str, password: str) -> bytes:
        # Return a deterministic placeholder private key for local testing
        return b"0" * 32
