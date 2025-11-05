import concurrent.futures
import json
import os

from pyutils.exchange_connectors import ConnectorType
from pyutils.gas_pricing.eth import GasPriceTracker, PriorityFee
from pyutils.exchange_apis.lyra_api import *
from pantheon import Pantheon
from pantheon.pantheon_types import Side

# For type annotations
from collections import defaultdict
from decimal import Decimal
from typing import Tuple
from web3 import Web3

from py_dex_common.dexes.dex_common import DexCommon
from py_dex_common.web_server import WebServer

from pyutils.exchange_connectors import ConnectorFactory, ConnectorType
from pyutils.exchange_apis import ApiFactory

# Helper class and some static functions so that the signing works nicely in the process poll
# Do the order signing here and not in pyutils so we can use the eth sig utils lib and be a lot faster.


class SigningData:
    def __init__(
        self,
        address: str,
        key: bytes,
        trade_module_address: str,
        withdraw_module_address: str,
        deposit_module_address: str,
        domain_separator: str,
        action_typehash: str,
        cash_address: str,
        risk_manager_addresses: str,
        rfq_module_address: str
    ):
        self.address = address
        self.key = key
        self.trade_module_address = trade_module_address
        self.withdraw_module_address = withdraw_module_address
        self.deposit_module_address = deposit_module_address
        self.domain_separator = domain_separator
        self.action_typehash = action_typehash
        self.cash_address = cash_address
        self.risk_manager_addresses = risk_manager_addresses
        self.rfq_module_address = rfq_module_address


class Order:
    def __init__(self, req_id, limit_price, amount, max_fee, subaccount_id, is_buy, nonce, sig_expiry, asset_address, asset_sub_id):
        self.req_id = req_id
        self.limit_price = limit_price
        self.amount = amount
        self.max_fee = max_fee
        self.subaccount_id = subaccount_id
        self.is_buy = is_buy
        self.nonce = nonce
        self.signature_expiry_sec = sig_expiry
        self.asset_address = asset_address
        self.asset_sub_id = asset_sub_id


class QuoteLeg:
    def __init__(self, quantity: Decimal, price: Decimal, side: Side,
                 asset_address: str, asset_sub_id: int):
        self.quantity = quantity
        self.side = side
        self.price = price
        self.asset_address = asset_address
        self.asset_sub_id = asset_sub_id


class Quote:
    def __init__(self, req_id: int, priced_legs: list[QuoteLeg], side: Side,
                 max_fee: Decimal, subaccount_id: int, nonce: int,
                 signature_expiry_sec: int):
        self.req_id = req_id
        self.priced_legs = priced_legs
        self.side = side
        self.max_fee = max_fee
        self.subaccount_id = subaccount_id
        self.nonce = nonce
        self.signature_expiry_sec = signature_expiry_sec


def encode_order_data(order: Order):
    encoded_data = encode(
        ["address", "uint", "int", "int", "uint", "uint", "bool"],
        [order.asset_address, order.asset_sub_id, order.limit_price, order.amount, order.max_fee, order.subaccount_id, order.is_buy],
    )

    return Web3.keccak(encoded_data)


def encode_priced_legs(quote: Quote) -> list[tuple[str, int, int, int]]:
    encoded_legs = []

    encoded_quote_direction = 1 if quote.side == Side.BUY else -1
    for leg in quote.priced_legs:
        encoded_leg_direction = 1 if leg.side == Side.BUY else -1
        signed_price = leg.price
        signed_amount = leg.quantity * encoded_leg_direction * encoded_quote_direction
        encoded_legs.append((leg.asset_address,
                             leg.asset_sub_id,
                             signed_price,
                             signed_amount))

    return encoded_legs


def encode_quote_data(quote: Quote) -> bytes:
    encoded_legs = encode_priced_legs(quote)
    quote_data = (quote.max_fee, encoded_legs)
    quote_data_abi = ["(uint,(address,uint,uint,int)[])"]
    encoded_data = encode(quote_data_abi, [quote_data])
    hashed_data = w3.keccak(hexstr=w3.to_hex(encoded_data)[2:])

    return hashed_data


def encode_subaccount_withdraw_data(cash_address: str, native_amount: int):
    encoded_data = encode(["address", "uint256"], [cash_address, native_amount])
    return Web3.keccak(encoded_data)


def encode_subaccount_deposit_data(cash_address: str, risk_manager_address: str, native_amount: int):
    encoded_data = encode(
        ["uint256", "address", "address"],
        [native_amount, cash_address, risk_manager_address],
    )
    return Web3.keccak(encoded_data)


def generate_order_signature(signing_data: SigningData, order: Order) -> str:
    start = time.time()
    encoded_data_hashed = encode_order_data(order)

    return generate_signature(
        encoded_data_hashed=encoded_data_hashed,
        signing_start_time=start,
        signing_data=signing_data,
        req_id=order.req_id,
        nonce=order.nonce,
        subaccount_id=order.subaccount_id,
        signature_expiry_sec=order.signature_expiry_sec,
        module_address=signing_data.trade_module_address,
    )


def generate_quote_signature(signing_data: SigningData, quote: Quote) -> str:
    start = time.time()
    encoded_data_hashed = encode_quote_data(quote)

    return generate_signature(
        encoded_data_hashed=encoded_data_hashed,
        signing_start_time=start,
        signing_data=signing_data,
        req_id=quote.req_id,
        nonce=quote.nonce,
        subaccount_id=quote.subaccount_id,
        signature_expiry_sec=quote.signature_expiry_sec,
        module_address=signing_data.rfq_module_address
    )


def generate_subaccount_withdraw_signature(
    signing_data: SigningData, req_id: int, native_amount: int, nonce: int, subaccount_id: int, signature_expiry_sec: int
):
    start = time.time()
    encoded_data_hashed = encode_subaccount_withdraw_data(signing_data.cash_address, native_amount)

    return generate_signature(
        encoded_data_hashed=encoded_data_hashed,
        signing_start_time=start,
        signing_data=signing_data,
        req_id=req_id,
        nonce=nonce,
        subaccount_id=subaccount_id,
        signature_expiry_sec=signature_expiry_sec,
        module_address=signing_data.withdraw_module_address,
    )


def generate_subaccount_deposit_signature(
    signing_data: SigningData,
    req_id: int,
    native_amount: int,
    nonce: int,
    subaccount_id: int,
    signature_expiry_sec: int,
    subaccount_type: str,
):
    start = time.time()
    encoded_data_hashed = encode_subaccount_deposit_data(
        signing_data.cash_address, signing_data.risk_manager_addresses[subaccount_type], native_amount
    )

    return generate_signature(
        encoded_data_hashed=encoded_data_hashed,
        signing_start_time=start,
        signing_data=signing_data,
        req_id=req_id,
        nonce=nonce,
        subaccount_id=subaccount_id,
        signature_expiry_sec=signature_expiry_sec,
        module_address=signing_data.deposit_module_address,
    )


def generate_signature(
    encoded_data_hashed,
    signing_start_time: float,
    signing_data: SigningData,
    req_id: int,
    nonce: int,
    subaccount_id: int,
    signature_expiry_sec: int,
    module_address: str,
) -> str:
    action_data = encode(
        ["bytes32", "uint256", "uint256", "address", "bytes32", "uint256", "address", "address"],
        [
            Web3.to_bytes(hexstr=signing_data.action_typehash),
            subaccount_id,
            nonce,
            module_address,
            encoded_data_hashed,
            signature_expiry_sec,
            signing_data.address,
            signing_data.address,
        ],
    )

    action_hash = Web3.keccak(action_data)

    buffer = Web3.to_bytes(hexstr="1901") + Web3.to_bytes(hexstr=signing_data.domain_separator) + action_hash
    typed_data_hash = Web3.keccak(buffer)

    signature = Account._sign_hash(Web3.to_bytes(typed_data_hash), signing_data.key).signature.hex()

    return signature


class Lyra(DexCommon):
    def __init__(self, pantheon: Pantheon, config: dict, server: WebServer, event_sink):
        super().__init__(pantheon, config, server, event_sink)
        
        api_factory = ApiFactory(ConnectorFactory(config["connectors"]))
        self._api = api_factory.create(self.pantheon, ConnectorType.Lyra)

        self.__register_endpoints(server)

        self.__chain_name = config["chain_name"]

        self.__gas_price_tracker = GasPriceTracker(pantheon, config["gas_price_tracker"])

        self.__process_pool = concurrent.futures.ProcessPoolExecutor(max_workers=config["max_signature_generators"])

        self.order_req_id = 0

        self.__bidding_wallet_whitelist = []
        self.__bidding_subaccount_whitelist = []
        self.__lyra_chain_withdrawal_addresses_whitelist = defaultdict(set)

    def __register_endpoints(self, server: WebServer) -> None:
        server.register("POST", "/private/create-account", self.__create_account)
        server.register("POST", "/private/create-subaccount", self.__create_subaccount)
        server.register("GET", "/private/get-account-details", self.__get_account)
        server.register("GET", "/private/get-subaccount-details", self.__get_subaccount)
        # server.register("GET", "/private/get-withdraw-from-l2-status", self.__get_withdrawal_from_l2_status)
        # server.register("POST", "/private/withdraw-from-l2-prove", self.__withdraw_from_l2_prove)
        # server.register("POST", "/private/withdraw-from-l2-finalise", self.__withdraw_from_l2_finalise)

        server.register("POST", "/private/login-signature", self.__sign_login_request)
        server.register("POST", "/private/order-signature", self.__sign_order_request)
        server.register("POST", "/private/quote-signature", self.__sign_quote_request)

        server.register("POST", "/private/approve-deposit-to-subaccount", self.__approve_deposit_to_subaccount)
        server.register("POST", "/private/approve-withdraw-from-subaccount", self.__approve_withdraw_from_subaccount)

        server.register("POST", "/private/deposit-from-l2-to-subaccount", self.__deposit_from_l2_wallet_to_subaccount)
        server.register("POST", "/private/withdraw-from-subaccount-to-l2", self.__withdraw_from_subaccount_to_l2_wallet)

        server.register("POST", "/private/approve-deposit-into-l2", self.__approve_deposit_into_l2)
        server.register("POST", "/private/approve-withdraw-from-l2", self.__approve_withdraw_from_l2)

        server.register("POST", "/private/deposit-into-l2", self.__deposit_into_l2)
        server.register("POST", "/private/withdraw-from-l2", self.__withdraw_from_l2)
        server.register("POST", "/private/withdraw-to-peer-l2-wallet", self.transfer)

        server.register("GET", "/private/get-l2-balance", self.__get_l2_balance)

        server.register("POST", "/private/transfer-position", self.__transfer_position)
        server.register("POST", "/private/request-eject-subaccount-from-trading", self.__request_eject_subaccount_from_trading)
        server.register("POST", "/private/transfer-bidding-subaccount-ownership", self.__transfer_bidding_subaccount_ownership)

    async def start(self, eth_private_key: str):
        bridge_details = self.__load_whitelist()

        await self._api.initialize(private_key_or_mnemonic=eth_private_key, bridge_details=bridge_details)

        await super().start(eth_private_key)

        await self.__gas_price_tracker.start()
        await self.__gas_price_tracker.wait_gas_price_ready()

        max_nonce_cached = self._request_cache.get_max_nonce()

        self._logger.info('Initializing nonce for l1 api')
        self._api.initialize_starting_nonce(max_nonce_cached + 1)

        self._logger.info('Initializing nonce for l2 api')
        self._api.l2_api.initialize_starting_nonce(0)

        def __assert(field, field_name) -> None:
            assert field is not None, f"{field_name} is None"

        __assert(self._api.l2_api._wallet_address, "wallet_address")
        __assert(self._api.l2_api._account.key, "account.key")
        __assert(self._api.l2_api.trade_module_address, "trade_module_address")
        __assert(self._api.l2_api.withdraw_module_address, "withdraw_module_address")
        __assert(self._api.l2_api.deposit_module_address, "deposit_module_adress")
        __assert(self._api.l2_api.domain_separator, "domain_separator")
        __assert(self._api.l2_api.action_typehash, "action_typehash")
        __assert(self._api.l2_api.cash_addresses, "cash_addresses")
        __assert(self._api.l2_api.risk_manager_addresses, "risk_manager_addresses")
        __assert(self._api.l2_api.rfq_module_address, "rfq_module_addresss")

        self.order_signing_data = SigningData(
            self._api.l2_api._wallet_address,
            self._api.l2_api._account.key,
            self._api.l2_api.trade_module_address,
            self._api.l2_api.withdraw_module_address,
            self._api.l2_api.deposit_module_address,
            self._api.l2_api.domain_separator,
            self._api.l2_api.action_typehash,
            self._api.l2_api.cash_addresses['USDC'],
            self._api.l2_api.risk_manager_addresses,
            self._api.l2_api.rfq_module_address
        )

        self.started = True

    def __load_whitelist(self) -> dict:
        file_prefix = os.path.dirname(os.path.realpath(__file__))
        addresses_whitelists_file_path = f"{file_prefix}/../../resources/lyra_contracts_address.json"
        self._logger.debug(f"Loading addresses whitelists from {addresses_whitelists_file_path}")
        with open(addresses_whitelists_file_path, "r") as contracts_address_file:
            contracts_address_json = json.load(contracts_address_file)[self.__chain_name]

            tokens_list_json = contracts_address_json["tokens"]
            for token_json in tokens_list_json:
                symbol = token_json["symbol"]
                if symbol in self._withdrawal_address_whitelists_from_res_file:
                    raise RuntimeError(f"Duplicate token : {symbol} in contracts_address file")
                for withdrawal_address in token_json["valid_withdrawal_addresses"]:
                    self._withdrawal_address_whitelists_from_res_file[symbol].add(Web3.to_checksum_address(withdrawal_address))

            lyra_tokens_list_json = contracts_address_json.get("lyra_chain_tokens", None)
            if lyra_tokens_list_json is not None:
                for token_json in lyra_tokens_list_json:
                    symbol = token_json["symbol"]
                    if symbol in self.__lyra_chain_withdrawal_addresses_whitelist:
                        raise RuntimeError(f"Duplicate lyra chain token : {symbol} in contracts_address file")
                    for withdrawal_address in token_json["valid_withdrawal_addresses"]:
                        self.__lyra_chain_withdrawal_addresses_whitelist[symbol].add(Web3.to_checksum_address(withdrawal_address))

            whitelisted_bidding_wallets_json = contracts_address_json["whitelisted_bidding_wallets"]
            for address in whitelisted_bidding_wallets_json:
                self.__bidding_wallet_whitelist.append(address)

            whitelisted_bidding_subaccount_ids_json = contracts_address_json["whitelisted_bidding_subaccount_ids"]
            for subaccount_id in whitelisted_bidding_subaccount_ids_json:
                self.__bidding_subaccount_whitelist.append(subaccount_id)

            return contracts_address_json["bridge_details"]

    def __assert_login_request_schema(self, received_keys: list) -> None:
        expected_keys = ["timestamp_ms"]

        assert len(received_keys) == len(
            expected_keys
        ), f"Request does not contain the correct set of fields. Expected [{', '.join(expected_keys)}]"
        for key in expected_keys:
            assert key in received_keys, f"Missing field({key}) in the request"

    def __assert_order_request_schema(self, received_keys: list) -> None:
        expected_keys = [
            "limit_price",
            "amount",
            "max_fee",
            "subaccount_id",
            "direction",
            "nonce",
            "signature_expiry_sec",
            "asset_sub_id",
            "asset_address",
        ]

        assert len(received_keys) == len(
            expected_keys
        ), f"Request does not contain the correct set of fields. Expected [{', '.join(expected_keys)}]"
        for key in expected_keys:
            assert key in received_keys, f"Missing field({key}) in the request"

    def __assert_quote_request_schema(self, received_keys: list) -> None:
        expected_keys = [
            "priced_legs",
            "direction",
            "max_fee",
            "subaccount_id",
            "nonce",
            "signature_expiry_sec",
            "asset_address",
            "asset_sub_ids"
        ]

        assert len(received_keys) == len(
            expected_keys
        ), f"Request does not contain the correct set of fields. Expected [{', '.join(expected_keys)}]"
        for key in expected_keys:
            assert key in received_keys, f"Missing field({key}) in the request"

    def __assert_subaccount_deposit_request_schema(self, received_keys: list) -> None:
        expected_keys = ["client_request_id", "amount", "symbol", "subaccount_id", "subaccount_type"]

        assert len(received_keys) == len(
            expected_keys
        ), f"Request does not contain the correct set of fields. Expected [{', '.join(expected_keys)}]"
        for key in expected_keys:
            assert key in received_keys, f"Missing field({key}) in the request"

    def __assert_subaccount_withdraw_request_schema(self, received_keys: list) -> None:
        expected_keys = ["client_request_id", "amount", "symbol", "subaccount_id"]

        assert len(received_keys) == len(
            expected_keys
        ), f"Request does not contain the correct set of fields. Expected [{', '.join(expected_keys)}]"
        for key in expected_keys:
            assert key in received_keys, f"Missing field({key}) in the request"

    async def __create_account(self, path: str, params: dict, received_at_ms: int) -> Tuple[int, dict]:
        try:
            account = await self._api.l2_api.create_account()
            return 200, {"account": account}
        except Exception as e:
            self._logger.exception(e)
            return 400, {"error": str(e)}

    async def __get_account(self, path: str, params: dict, received_at_ms: int) -> Tuple[int, dict]:
        try:
            account = await self._api.l2_api.get_account()
            return 200, {"account": account}
        except Exception as e:
            self._logger.exception(e)
            return 400, {"error": str(e)}

    async def __create_subaccount(self, path: str, params: dict, received_at_ms: int) -> Tuple[int, dict]:
        try:
            assert (
                params["subaccount_type"] == "PM_BTC" or params["subaccount_type"] == "PM_ETH" or params["subaccount_type"] == "SM"
            ), "Unknown subaccount_type"
            subaccount_type = params["subaccount_type"]

            response = await self._api.l2_api.create_subaccount(subaccount_type)
            return 200, {"response": response}
        except Exception as e:
            self._logger.exception(e)
            return 400, {"error": str(e)}

    async def __get_subaccount(self, path: str, params: dict, received_at_ms: int) -> Tuple[int, dict]:
        try:
            subaccount_id = params["subaccount_id"]
            subaccount = await self._api.l2_api.get_subaccount(subaccount_id)
            return 200, {"subaccount": subaccount}
        except Exception as e:
            self._logger.exception(e)
            return 400, {"error": str(e)}

    async def __sign_login_request(self, path: str, params: dict, received_at_ms: int) -> Tuple[int, dict]:
        try:
            self.__assert_login_request_schema(params.keys())
            signature = self._api.l2_api.get_request_signature(str(params["timestamp_ms"]))
            return 200, {"signature": signature}
        except Exception as e:
            return 400, {"error": str(e)}

    async def __sign_order_request(self, path: str, params: dict, received_at_ms: int) -> Tuple[int, dict]:
        try:
            req_id = self.order_req_id
            self.order_req_id += 1

            start = time.time()

            self._logger.debug(f"sign order request ({req_id}) received at {start}")

            self.__assert_order_request_schema(params.keys())

            order = Order(
                req_id,
                int(Decimal(params["limit_price"]) * int(1e18)),
                int(Decimal(params["amount"]) * int(1e18)),
                int(Decimal(params["max_fee"]) * int(1e18)),
                int(params["subaccount_id"]),
                params["direction"] == "buy",
                int(params["nonce"]),
                int(params["signature_expiry_sec"]),
                params["asset_address"],
                int(params["asset_sub_id"]),
            )

            msg_signature = await self.pantheon.loop.run_in_executor(
                self.__process_pool, generate_order_signature, self.order_signing_data, order
            )

            end = time.time()
            sign_time = (end - start) * 1000

            self._logger.debug(f"order request ({req_id}) signature => {msg_signature}, took {sign_time} ms")

            return 200, {"signature": msg_signature}

        except Exception as e:
            self._logger.exception(e)
            return 400, {"error": str(e)}

    async def __sign_quote_request(self, path: str, params: dict, received_at_ms: int) -> Tuple[int, dict]:
        try:
            req_id = self.order_req_id
            self.order_req_id += 1

            start = time.time()

            self._logger.debug(f"sign quote request ({req_id}) received at {start}")

            self.__assert_quote_request_schema(params.keys())

            priced_legs: list[QuoteLeg] = []
            for idx, leg in enumerate(params["priced_legs"]):
                priced_legs.append(QuoteLeg(
                    quantity=int(Decimal(leg["amount"]) * int(1e18)),
                    side=Side.BUY if leg["direction"] == "buy" else Side.SELL,
                    price=int(Decimal(leg["price"]) * int(1e18)),
                    asset_address=params["asset_address"],
                    asset_sub_id=params["asset_sub_ids"][idx]
                ))

            quote = Quote(
                req_id=req_id,
                priced_legs=priced_legs,
                side=Side.BUY if params["direction"] == "buy" else Side.SELL,
                max_fee=int(Decimal(params["max_fee"]) * int(1e18)),
                subaccount_id=params["subaccount_id"],
                nonce=params["nonce"],
                signature_expiry_sec=params["signature_expiry_sec"]
            )

            msg_signature = await self.pantheon.loop.run_in_executor(
                self.__process_pool, generate_quote_signature, self.order_signing_data, quote
            )

            end = time.time()
            sign_time = (end - start) * 1000

            self._logger.debug(f"quote request ({req_id}) signature => {msg_signature}, took {sign_time} ms")

            return 200, {"signature": msg_signature}

        except Exception as e:
            self._logger.exception(e)

    async def __approve_deposit_to_subaccount(self, path: str, params: dict, received_at_ms: int) -> Tuple[int, dict]:
        client_request_id = ""
        try:
            approve = self.__get_approve_request_obj(path, params, received_at_ms)
            self.__mark_as_l2_request(approve)
            self._logger.info(f"Approving={approve}, request_path={path}")

            self._request_cache.add(approve)

            result = await self._api.approve_deposit_into_l2_subaccount(approve.symbol, approve.amount)
            return self.__handle_approve_response(result, approve)
        except Exception as e:
            self._logger.exception(f"Failed to approve: %r", e)
            self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
            return 400, {"error": {"message": str(e)}}

    async def __approve_withdraw_from_subaccount(self, path: str, params: dict, received_at_ms: int) -> Tuple[int, dict]:
        client_request_id = ""
        try:
            approve = self.__get_approve_request_obj(path, params, received_at_ms)
            self.__mark_as_l2_request(approve)
            self._logger.info(f"Approving={approve}, request_path={path}")

            self._request_cache.add(approve)

            result = await self._api.approve_withdraw_from_l2_subaccount(approve.symbol, approve.amount)
            return self.__handle_approve_response(result, approve)
        except Exception as e:
            self._logger.exception(f"Failed to approve: %r", e)
            self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
            return 400, {"error": {"message": str(e)}}

    async def __deposit_from_l2_wallet_to_subaccount(self, path: str, params: dict, received_at_ms: int) -> Tuple[int, dict]:
        client_request_id = ""
        try:
            req_id = self.order_req_id
            self.order_req_id += 1

            start = time.time()

            self._logger.debug(f"deposit from l2 wallet to subaccount request ({req_id}) received at {start}")

            self.__assert_subaccount_deposit_request_schema(params.keys())

            client_request_id = params["client_request_id"]
            if self._request_cache.get(client_request_id) is not None:
                return 400, {"error": {"message": f"client_request_id={client_request_id} is already known"}}

            amount = Decimal(params["amount"])
            symbol = params["symbol"]
            subaccount_id = int(params["subaccount_id"])
            subaccount_type = params["subaccount_type"]

            signature_expiry_sec = int(start) + 600

            random_suffix = int(random.random() * 999)
            start_ms = int(start * 1000)
            nonce = int(f"{start_ms}{random_suffix}")

            transfer = TransferRequest(
                client_request_id=client_request_id,
                symbol=symbol,
                amount=amount,
                # Leaving this empty as the `address_to` is hardcoded in the
                # pyutils api call and is our L1 wallet address
                address_to="",
                # Unused
                gas_limit=0,
                request_path=path,
                received_at_ms=received_at_ms,
                dex_specific={
                    "chain": "L2",
                    "subaccount_id": subaccount_id,
                    "subaccount_type": subaccount_type,
                    "signature_expiry_sec": signature_expiry_sec,
                    "nonce": nonce,
                },
            )

            self._request_cache.add(transfer)

            transfer_signing_data = SigningData(
                self._api.l2_api._wallet_address,
                self._api.l2_api._account.key,
                self._api.l2_api.trade_module_address,
                self._api.l2_api.withdraw_module_address,
                self._api.l2_api.deposit_module_address,
                self._api.l2_api.domain_separator,
                self._api.l2_api.action_typehash,
                self._api.l2_api.cash_addresses[symbol],
                self._api.l2_api.risk_manager_addresses,
                self._api.l2_api.rfq_module_address
            )

            native_amount = self.__get_native_amount(symbol, amount)
            deposit_signature = await self.pantheon.loop.run_in_executor(
                self.__process_pool,
                generate_subaccount_deposit_signature,
                transfer_signing_data,
                req_id,
                native_amount,
                nonce,
                subaccount_id,
                signature_expiry_sec,
                subaccount_type,
            )

            got_sign_at = time.time()
            sign_time = (got_sign_at - start) * 1000

            self._logger.debug(
                f"subaccount deposit request ({req_id}) signature => {deposit_signature}, got sign at {got_sign_at}, took {sign_time} ms"
            )

            self._logger.debug(f"Transferring={transfer}, request_path={path}")
            result: dict = await self._api.l2_api.transfer_l2_wallet_to_subaccount(
                amount, symbol, nonce, subaccount_id, subaccount_type, signature_expiry_sec, deposit_signature
            )

            if result.get("transaction_id") is not None:
                tx_hash = result.get("transaction_id")
                transfer.tx_hashes.append((tx_hash, RequestType.TRANSFER.name))
                self._transactions_status_poller.add_for_polling(tx_hash, client_request_id, RequestType.TRANSFER)
                self._request_cache.maybe_add_or_update_request_in_redis(client_request_id)
                return 200, {"tx_hash": tx_hash}
            else:
                self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
                return 400, {
                    "error": {
                        "code": ErrorType.TRANSACTION_FAILED.value,
                        "message": "no transaction_id in response",
                        "api_response": result,
                    }
                }
        except Exception as e:
            self._logger.exception(f"Failed to transfer: %r", e)
            self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
            return 400, {"error": {"message": str(e)}}

    async def __withdraw_from_subaccount_to_l2_wallet(self, path: str, params: dict, received_at_ms: int) -> Tuple[int, dict]:
        client_request_id = ""
        try:
            req_id = self.order_req_id
            self.order_req_id += 1

            start = time.time()

            self._logger.debug(f"withdraw from subaccount to l2 wallet request ({req_id}) received at {start}")

            self.__assert_subaccount_withdraw_request_schema(params.keys())

            client_request_id = params["client_request_id"]
            if self._request_cache.get(client_request_id) is not None:
                return 400, {"error": {"message": f"client_request_id={client_request_id} is already known"}}

            amount = Decimal(params["amount"])
            symbol = params["symbol"]
            subaccount_id = int(params["subaccount_id"])

            signature_expiry_sec = int(start) + 600

            random_suffix = int(random.random() * 999)
            start_ms = int(start * 1000)
            nonce = int(f"{start_ms}{random_suffix}")

            transfer = TransferRequest(
                client_request_id=client_request_id,
                symbol=symbol,
                amount=amount,
                # Leaving this empty as the `address_to` is hardcoded in the
                # pyutils api call and is our L1 wallet address
                address_to="",
                # Unused
                gas_limit=0,
                request_path=path,
                received_at_ms=received_at_ms,
                dex_specific={"chain": "L2", "subaccount_id": subaccount_id, "signature_expiry_sec": signature_expiry_sec, "nonce": nonce},
            )

            self._request_cache.add(transfer)

            transfer_signing_data = SigningData(
                self._api.l2_api._wallet_address,
                self._api.l2_api._account.key,
                self._api.l2_api.trade_module_address,
                self._api.l2_api.withdraw_module_address,
                self._api.l2_api.deposit_module_address,
                self._api.l2_api.domain_separator,
                self._api.l2_api.action_typehash,
                self._api.l2_api.cash_addresses[symbol],
                self._api.l2_api.risk_manager_addresses,
                self._api.l2_api.rfq_module_address
            )

            native_amount = self.__get_native_amount(symbol, amount)
            withdraw_signature = await self.pantheon.loop.run_in_executor(
                self.__process_pool,
                generate_subaccount_withdraw_signature,
                transfer_signing_data,
                req_id,
                native_amount,
                nonce,
                subaccount_id,
                signature_expiry_sec,
            )

            got_sign_at = time.time()
            sign_time = (got_sign_at - start) * 1000

            self._logger.debug(
                f"subaccount withdraw request ({req_id}) signature => {withdraw_signature}, got sign at {got_sign_at}, took {sign_time} ms"
            )

            self._logger.debug(f"Transferring={transfer}, request_path={path}")
            result: dict = await self._api.l2_api.transfer_subaccount_to_l2_wallet(
                amount,
                symbol,
                nonce,
                subaccount_id,
                signature_expiry_sec,
                withdraw_signature,
            )

            if result.get("transaction_id") is not None:
                tx_hash = result.get("transaction_id")
                transfer.tx_hashes.append((tx_hash, RequestType.TRANSFER.name))
                self._transactions_status_poller.add_for_polling(tx_hash, client_request_id, RequestType.TRANSFER)
                self._request_cache.maybe_add_or_update_request_in_redis(client_request_id)
                return 200, {"tx_hash": tx_hash}
            else:
                self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
                return 400, {
                    "error": {
                        "code": ErrorType.TRANSACTION_FAILED.value,
                        "message": "no transaction_id in response",
                        "api_response": result,
                    }
                }
        except Exception as e:
            self._logger.exception(f"Failed to transfer: %r", e)
            self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
            return 400, {"error": {"message": str(e)}}

    # We don't need to do anything special on a new client connection
    async def on_new_connection(self, _):
        return

    async def process_request(self, ws, request_id: str, method: str, params: dict):
        return False

    def __mark_as_l2_request(self, request: Request) -> None:
        request.dex_specific = {"chain": "L2"}

    def __is_l2_request(self, request: Request) -> bool:
        return request.dex_specific and (request.dex_specific.get("chain", "") == "L2")

    async def _approve(self, request, gas_price_wei: int, nonce: int = None):
        raise Exception(f"The endpoint is not supported in Lyra")

    def __allow_lyra_withdraw(self, client_request_id, symbol, address_to):
        if symbol not in self.__lyra_chain_withdrawal_addresses_whitelist:
            self._logger.error(
                f'HIGH ALERT: client_request_id={client_request_id} tried to withdraw unknown token={symbol} on lyra')
            return False, f'Unknown token={symbol} on lyra'

        assert address_to is not None
        if Web3.to_checksum_address(address_to) not in self.__lyra_chain_withdrawal_addresses_whitelist[symbol]:
            self._logger.error(
                f'HIGH ALERT: client_request_id={client_request_id} tried to withdraw token={symbol} '
                f'to unknown address={address_to} on lyra chain')
            return False, f'Unknown withdrawal_address={address_to} for token={symbol} on lyra chain'

        return True, ''

    async def _transfer(
        self, request, gas_price_wei: int, nonce: int = None,
    ):
        if request.request_path == "/private/withdraw":
            assert request.address_to is not None
            return await self._api.withdraw(request.symbol, request.address_to, request.amount,
                                            request.gas_limit, gas_price_wei)
        if request.request_path == "/private/withdraw-to-peer-l2-wallet":
            assert request.address_to is not None

            self.__mark_as_l2_request(request)

            ok, reason = self.__allow_lyra_withdraw(request.client_request_id, request.symbol,
                                              request.address_to)
            if not ok:
                raise RuntimeError(reason)

            return await self._api.l2_api.withdraw(request.symbol,
                                                   request.address_to,
                                                   request.amount,
                                                   request.gas_limit,
                                                   gas_price_wei)
        else:
            assert False

    async def _amend_transaction(self, request: Request, params, gas_price_wei):
        if request.request_type == RequestType.TRANSFER:
            if request.request_path == "/private/withdraw":
                return await self._api.withdraw(
                    request.symbol, request.address_to, request.amount, request.gas_limit, gas_price_wei, nonce=request.nonce
                )
            elif request.request_path == "/private/deposit-into-l2":
                return await self._api.deposit_into_l2(
                    request.symbol, request.amount, request.gas_limit, gas_price=gas_price_wei, nonce=request.nonce
                )
            elif request.request_path == "/private/withdraw-to-peer-l2-wallet":
                return await self._api.l2_api.withdraw(
                    request.symbol, request.address_to, request.amount, request.gas_limit, gas_price_wei, nonce=request.nonce
                )
            else:
                raise Exception(f"Unsupported request_path={request.request_path} for amending transfer request")
        elif request.request_type == RequestType.APPROVE:
            if request.request_path == "/private/approve-deposit-into-l2":
                return await self._api.approve_deposit_into_l2(
                    request.symbol, request.amount, request.gas_limit, gas_price_wei, nonce=request.nonce
                )
            else:
                raise Exception(f"Unsupported request_path={request.request_path} for amending approve request")
        else:
            raise Exception("Unsupported request type for amending")

    async def _cancel_transaction(self, request: Request, gas_price_wei):
        if self.__is_l2_request(request):
            raise Exception("Cancelling L2 transactions is not supported")

        if request.request_type == RequestType.TRANSFER or request.request_type == RequestType.APPROVE:
            return await self._api.cancel_transaction(request.nonce, gas_price_wei)
        else:
            raise Exception(f"Cancelling not supported for the {request.request_type}")

    async def get_transaction_receipt(self, request, tx_hash: str):
        if not self.__is_l2_request(request):
            return await self._api.get_transaction_receipt(tx_hash)
        else:
            receipt = await self._api.get_l2_transaction_receipt(tx_hash)

            if tx_hash.startswith("0x"):
                return receipt
            else:
                status: str = receipt.get("status")
                if status == "settled":
                    return {"status": 1}
                elif status == "reverted" or status == "ignored":
                    return {"status": 0}
                else:  # All other states map to PENDING transaction
                    return None

    def _get_gas_price(self, request, priority_fee: PriorityFee):
        return self.__gas_price_tracker.get_gas_price(priority_fee=priority_fee)

    async def on_request_status_update(self, client_request_id, request_status, tx_receipt: dict, mined_tx_hash: str = None):
        super().on_request_status_update(client_request_id, request_status, tx_receipt, mined_tx_hash)

    async def _get_all_open_requests(self, path: str, params: dict, received_at_ms: int):
        return await super()._get_all_open_requests(path, params, received_at_ms)

    async def _cancel_all(self, path: str, params: dict, received_at_ms: int):
        try:
            assert params["request_type"] == "TRANSFER" or params["request_type"] == "APPROVE", "Unknown transaction type"

            request_type = RequestType[params["request_type"]]

            self._logger.debug(f"Canceling all requests, request_type={request_type.name}")

            cancel_requested = []
            failed_cancels = []

            for request in self._request_cache.get_all(request_type):
                # Only cancel L1 transactions
                if self.__is_l2_request(request):
                    continue
                try:
                    gas_price_wei = self._get_gas_price(request, priority_fee=PriorityFee.Fast)

                    if request.request_status == RequestStatus.CANCEL_REQUESTED and request.used_gas_prices_wei[-1] >= gas_price_wei:
                        self._logger.info(
                            f"Not sending cancel request for client_request_id={request.client_request_id} as cancel with "
                            f"greater than or equal to the gas_price_wei={gas_price_wei} already in progress"
                        )
                        cancel_requested.append(request.client_request_id)
                        continue

                    if len(request.used_gas_prices_wei) > 0:
                        gas_price_wei = max(gas_price_wei, int(1.1 * request.used_gas_prices_wei[-1]))

                    ok, reason = self._check_max_allowed_gas_price(gas_price_wei)
                    if not ok:
                        self._logger.error(f"Not sending cancel request for client_request_id={request.client_request_id}: {reason}")
                        failed_cancels.append(request.client_request_id)
                        continue

                    self._logger.debug(f"Canceling={request}, gas_price_wei={gas_price_wei}")
                    result = await self._cancel_transaction(request, gas_price_wei)

                    if result.error_type == ErrorType.NO_ERROR:
                        request.request_status = RequestStatus.CANCEL_REQUESTED
                        request.tx_hashes.append((result.tx_hash, RequestType.CANCEL.name))
                        request.used_gas_prices_wei.append(gas_price_wei)

                        cancel_requested.append(request.client_request_id)

                        self._transactions_status_poller.add_for_polling(result.tx_hash, request.client_request_id, RequestType.CANCEL)
                        self._request_cache.maybe_add_or_update_request_in_redis(request.client_request_id)
                    else:
                        failed_cancels.append(request.client_request_id)
                except Exception as ex:
                    self._logger.exception(f"Failed to cancel request={request.client_request_id}: %r", ex)
                    failed_cancels.append(request.client_request_id)
            return 400 if failed_cancels else 200, {"cancel_requested": cancel_requested, "failed_cancels": failed_cancels}

        except Exception as e:
            self._logger.exception(f"Failed to cancel all: %r", e)
            return 400, {"error": {"message": str(e)}}

    async def __approve_deposit_into_l2(self, path: str, params: dict, received_at_ms: int) -> Tuple[int, dict]:
        client_request_id = ""
        try:
            approve = self.__get_approve_request_obj(path, params, received_at_ms)

            gas_limit = int(params["gas_limit"])
            gas_price_wei = int(params["gas_price_wei"])
            ok, reason = self._check_max_allowed_gas_price(gas_price_wei)
            if not ok:
                return 400, {"error": {"message": reason}}
            approve.gas_limit = gas_limit

            self._logger.info(f"Approving={approve}, request_path={path}, gas_price_wei={gas_price_wei}")

            self._request_cache.add(approve)

            result = await self._api.approve_deposit_into_l2(approve.symbol, approve.amount, gas_limit, gas_price_wei)

            if result.error_type == ErrorType.NO_ERROR:
                approve.used_gas_prices_wei.append(gas_price_wei)

            return self.__handle_approve_response(result, approve)

        except Exception as e:
            self._logger.exception(f"Failed to approve: %r", e)
            self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
            return 400, {"error": {"message": str(e)}}

    async def __approve_withdraw_from_l2(self, path: str, params: dict, received_at_ms: int) -> Tuple[int, dict]:
        client_request_id = ""
        try:
            approve = self.__get_approve_request_obj(path, params, received_at_ms)
            self.__mark_as_l2_request(approve)
            self._logger.info(f"Approving={approve}, request_path={path}")

            self._request_cache.add(approve)

            result = await self._api.approve_withdraw_from_l2(approve.symbol, approve.amount)
            return self.__handle_approve_response(result, approve)
        except Exception as e:
            self._logger.exception(f"Failed to approve: %r", e)
            self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
            return 400, {"error": {"message": str(e)}}

    async def __deposit_into_l2(self, path: str, params: dict, received_at_ms: int):
        client_request_id = ""
        try:
            symbol = params["symbol"]

            client_request_id = params["client_request_id"]
            if self._request_cache.get(client_request_id) is not None:
                return 400, {"error": {"message": f"client_request_id={client_request_id} is already known"}}

            amount = Decimal(params["amount"])
            gas_limit = int(params["gas_limit"])

            transfer = TransferRequest(
                client_request_id=client_request_id,
                symbol=symbol,
                amount=amount,
                # Leaving this empty as the `address_to` is hardcoded in the
                # pyutils api call and is our l2 account address
                address_to="",
                gas_limit=gas_limit,
                request_path=path,
                received_at_ms=received_at_ms,
            )

            self._logger.info(f"Transferring={transfer}, request_path={path}")

            self._request_cache.add(transfer)

            result = await self._api.deposit_into_l2(symbol, amount, gas_limit)

            if result.error_type == ErrorType.NO_ERROR:
                transfer.nonce = result.nonce
                transfer.tx_hashes.append((result.tx_hash, RequestType.TRANSFER.name))

                self._transactions_status_poller.add_for_polling(result.tx_hash, client_request_id, RequestType.TRANSFER)
                self._request_cache.maybe_add_or_update_request_in_redis(client_request_id)
                return 200, {"tx_hash": result.tx_hash}
            else:
                self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
                return 400, {"error": {"code": result.error_type.value, "message": result.error_message}}
        except Exception as e:
            self._logger.exception(f"Failed to transfer: %r", e)
            self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
            return 400, {"error": {"message": str(e)}}

    async def __withdraw_from_l2(self, path: str, params: dict, received_at_ms: int):
        client_request_id = ""
        try:
            symbol = params["symbol"]
            gas_limit = int(params["gas_limit"])

            client_request_id = params["client_request_id"]
            if self._request_cache.get(client_request_id) is not None:
                return 400, {"error": {"message": f"client_request_id={client_request_id} is already known"}}

            amount = Decimal(params["amount"])

            transfer = TransferRequest(
                client_request_id=client_request_id,
                symbol=symbol,
                amount=amount,
                # Leaving this empty as the `address_to` is hardcoded in the
                # pyutils api call and is our L1 wallet address
                address_to="",
                gas_limit=gas_limit,
                request_path=path,
                received_at_ms=received_at_ms,
            )

            self.__mark_as_l2_request(transfer)

            self._logger.debug(f"Transferring={transfer}, request_path={path}")

            self._request_cache.add(transfer)

            result = await self._api.withdraw_from_l2(symbol, amount, gas_limit)

            if result.error_type == ErrorType.NO_ERROR:
                transfer.nonce = result.nonce
                transfer.tx_hashes.append((result.tx_hash, RequestType.TRANSFER.name))
                self._transactions_status_poller.add_for_polling(result.tx_hash, client_request_id, RequestType.TRANSFER)
                self._request_cache.maybe_add_or_update_request_in_redis(client_request_id)

                return 200, {"tx_hash": result.tx_hash}
            else:
                self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
                return 400, {"error": {"code": result.error_type.value, "message": result.error_message}}
        except Exception as e:
            self._logger.exception(f"Failed to transfer: %r", e)
            self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
            return 400, {"error": {"message": str(e)}}

    async def __get_l2_balance(self, path: str, params: dict, received_at_ms: int) -> Tuple[int, dict]:
        try:
            symbol = params["symbol"]
            balance = await self._api.get_l2_wallet_balance(symbol)
            return 200, {"balance": str(balance)}
        except Exception as e:
            return 400, {"error": {"message": repr(e)}}

    def __get_lyra_api_nonce(self) -> int:
        random_suffix = int(random.random() * 999)
        start_ms = int(time.time() * 1000)
        return int(f"{start_ms}{random_suffix}")

    async def __build_order_dict_for_position_transfer(self, instrument_name: str, subaccount_id: int, direction: str,
                                                       limit_price: str, amount: str, max_fee: str,
                                                       asset_address: str, asset_sub_id: str) -> dict:
        nonce = self.__get_lyra_api_nonce()
        signature_expiry = int(time.time()) + 600

        req_id = self.order_req_id
        self.order_req_id += 1

        order = Order(
            req_id,
            int(Decimal(limit_price) * int(1e18)),
            int(Decimal(amount) * int(1e18)),
            int(Decimal(max_fee) * int(1e18)),
            int(subaccount_id),
            direction == "buy",
            nonce,
            signature_expiry,
            asset_address,
            int(asset_sub_id),
        )

        signature = await self.pantheon.loop.run_in_executor(
            self.__process_pool, generate_order_signature, self.order_signing_data, order
        )

        return {
            'instrument_name': instrument_name,
            'direction': direction,
            'amount': amount,
            'limit_price': limit_price,
            'max_fee': max_fee,
            'nonce': nonce,
            'signature': signature,
            'signature_expiry_sec': signature_expiry,
            'signer': self._api.l2_api._wallet_address,
            'subaccount_id': subaccount_id,
        }

    '''
    Transferring a position means closing that position in the source account
    and opening the same position in the dest account. For example

    - Transferring a short -0.5 BTC-PERP position from A to B means
      buying 0.5 BTC-PERP in A and selling 0.5 BTC-PERP in B
    - Transferring a long 0.4 ETH-PERP position from A to B means
      selling 0.4 ETH-PERP in A and buying 0.4 ETH-PERP in B
    '''
    async def __transfer_position(self, path: str, params: dict, received_at_ms: int) -> Tuple[int, dict]:
        try:
            amount = params["amount"]
            max_fee = '0'
            limit_price = '1' # Anything > 0  will do herre I think

            amount_in_decimal = Decimal(amount)
            maker_direction = "buy" if amount_in_decimal < 0 else "sell"
            taker_direction = "buy" if maker_direction == "sell" else "sell"

            amount = str(abs(amount_in_decimal))

            maker_order = await self.__build_order_dict_for_position_transfer(params["instrument_name"],
                                                                              params["from_subaccount_id"],
                                                                              maker_direction,
                                                                              limit_price,
                                                                              amount,
                                                                              max_fee,
                                                                              params["asset_address"],
                                                                              params["asset_sub_id"])

            taker_order = await self.__build_order_dict_for_position_transfer(params["instrument_name"],
                                                                              params["to_subaccount_id"],
                                                                              taker_direction,
                                                                              limit_price,
                                                                              amount,
                                                                              max_fee,
                                                                              params["asset_address"],
                                                                              params["asset_sub_id"])

            response = await self._api.l2_api.transfer_position(maker_order, taker_order)

            return 200, {"transfer-position": str(response)}
        except Exception as e:
            return 400, {"error": {"message": repr(e)}}

    async def __request_eject_subaccount_from_trading(self, path: str, params: dict, received_at_ms: int) -> Tuple[int, dict]:
        try:
            subaccount_id = params["subaccount_id"]
            result = await self._api.l2_api.request_withdraw_subaccount(subaccount_id)
            if result.error_type == ErrorType.NO_ERROR:
                return 200, {"tx_hash": result.tx_hash}
            else:
                return 400, {"error": {"code": result.error_type.value, "message": result.error_message}}
        except Exception as e:
            return 400, {"error": {"message": repr(e)}}

    async def __transfer_bidding_subaccount_ownership(self, path: str, params: dict, received_at_ms: int) -> Tuple[int, dict]:
        try:
            subaccount_id = params["subaccount_id"]
            to_wallet = params["to_wallet"]

            if subaccount_id not in self.__bidding_subaccount_whitelist:
                return 400, {"error": {"message": "subaccount id not whitelisted for withdrawal"}}

            if to_wallet not in self.__bidding_wallet_whitelist:
                return 400, {"error": {"message": "wallet address not whitelisted for withdrawal"}}

            result = await self._api.l2_api.transfer_ownership_of_subaccount(self._api.l2_api._wallet_address, to_wallet, subaccount_id)
            if result.error_type == ErrorType.NO_ERROR:
                return 200, {"tx_hash": result.tx_hash}
            else:
                return 400, {"error": {"code": result.error_type.value, "message": result.error_message}}
        except Exception as e:
            return 400, {"error": {"message": repr(e)}}

    def __get_approve_request_obj(self, request_path: str, params: dict, received_at_ms: int) -> ApproveRequest:
        client_request_id = params["client_request_id"]
        if self._request_cache.get(client_request_id) is not None:
            raise Exception(f"client_request_id={client_request_id} is already known")

        symbol = params["symbol"]
        amount = Decimal(params["amount"])

        approve = ApproveRequest(
            client_request_id=client_request_id,
            symbol=symbol,
            amount=amount,
            gas_limit=0,
            request_path=request_path,
            received_at_ms=received_at_ms,
        )

        return approve

    def __handle_approve_response(self, result: ApiResult, approve: ApproveRequest) -> Tuple[int, dict]:
        if result.error_type == ErrorType.NO_ERROR:
            approve.nonce = result.nonce
            approve.tx_hashes.append((result.tx_hash, RequestType.APPROVE.name))
            self._transactions_status_poller.add_for_polling(result.tx_hash, approve.client_request_id, RequestType.APPROVE)
            self._request_cache.maybe_add_or_update_request_in_redis(approve.client_request_id)
            return 200, {"tx_hash": result.tx_hash}
        else:
            self._request_cache.finalise_request(approve.client_request_id, RequestStatus.FAILED)
            return 400, {"error": {"code": result.error_type.value, "message": result.error_message}}

    def __get_native_amount(self, symbol: str, amount: Decimal) -> int:
        if symbol == "ETH":
            return Web3.to_wei(amount, "ether")
        else:
            return self._api.to_native_amount(symbol, amount)

    # async def __get_withdrawal_from_l2_status(self, path: str, params: dict, received_at_ms: int) -> ApiResult:
    #     tx_hash = params["tx_hash"]

    #     try:
    #         result = await self._api.get_withdraw_from_l2_status(tx_hash)
    #         return 200, {"status": result.name}
    #     except Exception as e:
    #         return 400, {"error": {"message": repr(e)}}

    # async def __withdraw_from_l2_prove(self, path: str, params: dict, received_at_ms: int) -> ApiResult:
    #     tx_hash = params["tx_hash"]
    #     client_request_id = params["client_request_id"]

    #     result = await self._api.withdraw_from_l2_prove(tx_hash)

    #     if result.error_type == ErrorType.NO_ERROR:
    #         self._request_cache.maybe_add_or_update_request_in_redis(client_request_id)

    #         return 200, {"tx_hash": result.tx_hash}
    #     else:
    #         self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
    #         return 400, {"error": {"code": result.error_type.value, "message": result.error_message}}

    # async def __withdraw_from_l2_finalise(self, path: str, params: dict, received_at_ms: int) -> ApiResult:
    #     tx_hash = params["tx_hash"]
    #     client_request_id = params["client_request_id"]

    #     result = await self._api.withdraw_from_l2_prove(tx_hash)

    #     if result.error_type == ErrorType.NO_ERROR:
    #         self._request_cache.maybe_add_or_update_request_in_redis(client_request_id)
    #         return 200, {"tx_hash": result.tx_hash}
    #     else:
    #         self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
    #         return 400, {"error": {"code": result.error_type.value, "message": result.error_message}}
