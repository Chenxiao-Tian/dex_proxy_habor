"""Minimal subset of web3 used for testing."""


class Web3:
    @staticmethod
    def to_checksum_address(address: str) -> str:
        return address


class _ExceptionsModule:
    class TransactionNotFound(Exception):
        """Raised when a transaction cannot be located."""


exceptions = _ExceptionsModule()
