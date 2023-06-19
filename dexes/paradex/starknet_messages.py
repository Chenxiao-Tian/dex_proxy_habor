from decimal import Decimal


class StarknetMessages(object):
    @staticmethod
    def onboarding(chain_id: int) -> dict:
        msg = {
            "message": {
                "action": "Onboarding",
            },
            "domain": {
                "name": "Paradex",
                "chainId": hex(chain_id),
                "version": "1"
            },
            "primaryType": "Constant",
            "types": {
                "StarkNetDomain": [
                    {"name": "name", "type": "felt"},
                    {"name": "chainId", "type": "felt"},
                    {"name": "version", "type": "felt"},
                ],
                "Constant": [
                    {"name": "action", "type": "felt"},
                ],
            },
        }

        return msg


    @staticmethod
    def stark_key(chain_id: int) -> dict:
        msg = {
            "domain": {
                "name": "Paradex",
                "version": "1",
                "chainId": chain_id
            },
            "primaryType": "Constant",
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                ],
                "Constant": [
                    {"name": "action", "type": "string"},
                ],
            },
            "message": {
                "action": "STARK Key",
            },
        }

        return msg


    @staticmethod
    def authentication(chain_id: int, now: int, expiry: int) -> dict:
        msg = {
            "message": {
                "method": "POST",
                "path": "/v1/auth",
                "body": "",
                "timestamp": now,
                "expiration": expiry,
            },
            "domain": {
                "name": "Paradex",
                "chainId": hex(chain_id),
                "version": "1"
            },
            "primaryType": "Request",
            "types": {
                "StarkNetDomain": [
                    {"name": "name", "type": "felt"},
                    {"name": "chainId", "type": "felt"},
                    {"name": "version", "type": "felt"},
                ],
                "Request": [
                    {"name": "method", "type": "felt"},
                    {"name": "path", "type": "felt"},
                    {"name": "body", "type": "felt"},
                    {"name": "timestamp", "type": "felt"},
                    {"name": "expiration", "type": "felt"},
                ],
            },
        }

        return msg


    @staticmethod
    def order_request(
        chain_id: int,
        order_creation_ts_ms: int,
        market: str,
        side: str,
        order_type: str,
        size: str,
        price: str,
    ) -> dict:

        factor = Decimal(100_000_000)

        msg = {
            "domain": {
                "name": "Paradex",
                "chainId": hex(chain_id),
                "version": "1"
            },
            "primaryType": "Order",
            "types": {
                "StarkNetDomain": [
                    {"name": "name", "type": "felt"},
                    {"name": "chainId", "type": "felt"},
                    {"name": "version", "type": "felt"},
                ],
                "Order": [
                    # Time of signature request in ms since epoch
                    {"name": "timestamp", "type": "felt"},
                    # E.g.: "BTC-USD-PERP"
                    {"name": "market", "type": "felt"},
                    # 1: Buy or 2: Sell
                    {"name": "side", "type": "felt"},
                    # Limit or Market
                    {"name": "orderType", "type": "felt"},
                    # Integer value after multiplying size by 10**8
                    {"name": "size", "type": "felt"},
                    # Integer value after multiplying price by 10**8 or
                    # 0 for market orders
                    {"name": "price", "type": "felt"},
                ],
            },
            "message": {
                "timestamp": str(order_creation_ts_ms),
                "market": market,
                "side": 1 if side == "BUY" else 2,
                "orderType": order_type,
                "size": str(int(Decimal(size) * factor)),
                "price": str(int(Decimal(price) * factor))
            }
        }

        return msg
