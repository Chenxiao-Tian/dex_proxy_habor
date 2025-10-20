import aiohttp
import asyncio
import json
import os
import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from pantheon import Pantheon
from pantheon.instruments_source import (
    InstrumentKind,
    InstrumentLifecycle,
    InstrumentsLiveSource,
    InstrumentUsageExchanges,
)
from pantheon.pantheon_types import OrderType, Side
from pantheon.timestamp_ns import TimestampNs

from .drift_api import (
    Order,
    OrderStatus,
    decode_name,
    equal_drift_enum,
)
from .clients_pool import ClientsPool, DEFAULT_SUB_ACCOUNT_ID
from .event_subscribers import EventSubscribers
from .order_cache import OrderCache
from .rest_order_status_syncer import RestOrderStatusSyncer
from .makers import Makers
from .utils import (
    AccessMode,
    classify_cancel_error,
    classify_insert_error,
    full_order_to_dict,
    get_drift_market_type,
    order_to_dict,
    should_send_cancel_order_error,
)
from py_dex_common.dexes.dex_common import (
    ApiResult,
    ErrorType,
    RequestStatus,
    DexCommon,
)
from py_dex_common.web_server import WebServer

from solana.rpc.api import Client
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction
from spl.token.client import Token
from spl.token.constants import TOKEN_PROGRAM_ID
from spl.token.instructions import TransferParams, transfer

from driftpy.constants.numeric_constants import (
    BASE_PRECISION,
    MARGIN_PRECISION,
    PRICE_PRECISION,
    QUOTE_PRECISION,
)
from driftpy.drift_client import DriftClient
from driftpy.drift_user import DriftUser
from driftpy.math.amm import calculate_bid_ask_price
from driftpy.math.conversion import convert_to_number
from driftpy.math.margin import MarginCategory
from driftpy.types import (
    MarketStatus,
    MarketType as DriftMarketType,
    PositionDirection,
    PostOnlyParams,
    OrderParams,
    OrderParamsBitFlag,
    OrderType as DriftOrderType,
    market_type_to_string,
)


MAX_DRIFT_USER_ORDER_ID = 255
MAX_DUMMY_VALUE = 888888888
MARGIN_PRECISION_OVERRIDE = 10**6


class Drift(DexCommon):
    CHANNELS = ["ORDER", "TRADE"]

    def __get_mode_from_config(self, config: dict):
        try:
            return AccessMode[config.get("mode", "READONLY")]
        except KeyError:
            return AccessMode.READONLY

    def __init__(self, pantheon: Pantheon, config: dict, server: WebServer, event_sink):
        super().__init__(pantheon, config, server, event_sink)

        self.dex_access_mode = self.__get_mode_from_config(config)

        self._account = config["account"]
        self.solana_client = Client(config["url"])

        self.wallet_public_key: Pubkey = None
        self.user_public_key: Pubkey = None
        self._markets_refresh_interval_s = config["markets_refresh_interval_s"]

        self._spot_id2name = {}
        self._spot_name2id = {}
        self._perp_id2name = {}
        self._perp_name2id = {}

        self.perp_pnl_settlement_frequency = config.get(
            "perp_pnl_settlement_frequency", 120
        )

        self._clients_pool: ClientsPool = None

        # drift requires order_id to be 1~255, so we need to map our client order id into order id
        # https://github.com/drift-labs/gateway?tab=readme-ov-file#place-orders
        self._next_drift_user_order_id = 1

        self._order_cache = OrderCache(pantheon=pantheon, config=config["order_cache"])
        self._makers = Makers(config["makers"]) if "makers" in config else None

        # Initialize API configuration once
        api_config = config.get("api", {})
        self._api_base_url = api_config.get("base_url", "https://18j4mizwxe.execute-api.eu-west-1.amazonaws.com/live/")
        self._api_key = api_config.get("api_key", "hkugmRbuKV6fa6TO4jErl9LmYdLwOBJSyv3HgtO7")
        self._api_timeout_s = api_config.get("timeout_s", 10)

        self.instruments: Optional[InstrumentsLiveSource] = None

        name = config["name"]

        server.register(
            "GET",
            "/public/order",
            self._query_order,
            summary="Get a single order",
            tags=["public"],
        )
        server.register(
            "GET",
            "/public/orders",
            self._query_live_orders,
            summary="List all live orders",
            tags=["public"],
        )

        server.register("GET", "/public/portfolio", self._query_portfolio)
        server.register("GET", "/public/balance", self._get_balance)
        server.register("GET", "/public/user-info", self._get_user_info)
        server.register("GET", "/public/contract-data", self._get_contract_data)
        server.register("GET", "/public/margin-data", self._get_margin_data)
        server.register("GET", "/public/markets", self._fetch_markets)
        server.register("GET", "/public/transfers", self._fetch_transfer_records)
        server.register("GET", "/public/funding", self._fetch_funding_records)
        server.register("GET", "/public/trades", self._fetch_trades)

        if self.dex_access_mode == AccessMode.READWRITE:
            # https://drift-labs.github.io/v2-teacher/#user-initialization
            # account must be initialized to start trading
            # this needs to be called exactly once per account
            server.register(
                "POST",
                "/initialize-user",
                self._initialize_user,
                summary="Initialize user",
                tags=[name],
            )

            # https://drift-labs.github.io/v2-teacher/#manager-commands
            # these two endpoints are used to enable / disable spot trading
            # for the account in use
            server.register(
                "POST",
                "/enable-margin-trading",
                self._enable_margin_trading,
                summary="Enable margin trading",
                tags=[name],
            )
            server.register(
                "POST",
                "/disable-margin-trading",
                self._disable_margin_trading,
                summary="Disable margin trading",
                tags=[name],
            )

            server.register(
                "POST",
                "/private/create-order",
                self._create_order,
                summary="Create a new order",
                tags=["private"],
            )

            server.register(
                "DELETE",
                "/private/cancel-order",
                self._cancel_order,
                summary="Cancel a single order",
                tags=["private"],
            )
            server.register(
                "DELETE",
                "/private/cancel-all-orders",
                self._cancel_all_orders,
                summary="Cancel all orders",
                tags=["private"],
            )
            server.register("POST", "/private/deposit-token", self._deposit)
            server.register("POST", "/private/withdraw-token", self._withdraw)

        if self.dex_access_mode == AccessMode.READONLY:
            self._server.deregister("POST", "/private/approve-token")
            self._server.deregister("POST", "/private/withdraw")
            self._server.deregister("POST", "/private/amend-request")
            self._server.deregister("DELETE", "/private/cancel-request")
            self._server.deregister("DELETE", "/private/cancel-all")

    def __load_whitelist(self):
        file_prefix = os.path.dirname(os.path.realpath(__file__))
        self._withdrawal_address_whitelists = {}
        addresses_whitelists_file_path = (
            f"{file_prefix}/../../resources/drift_valid_addresses.json"
        )
        self._logger.debug(
            f"Loading addresses whitelists from {addresses_whitelists_file_path}"
        )
        with open(addresses_whitelists_file_path, "r") as contracts_address_file:
            contracts_address_json = json.load(contracts_address_file)
            for token_info in contracts_address_json["tokens"]:
                self._withdrawal_address_whitelists[token_info["token"]] = {
                    "mint": token_info["mint"],
                    "valid_withdrawal_addresses": token_info[
                        "valid_withdrawal_addresses"
                    ],
                    "decimals": token_info["decimals"],
                }

    def _get_market_status_name(self, status):
        status_str = str(status)
        # Extract text between '.' and '>' or '()'
        start = status_str.rfind(".") + 1
        end = status_str.find(">") if ">" in status_str else status_str.find("(")
        return status_str[start:end].lower()

    async def start(self, secret: Optional[list]):
        await super().start()
        self.__load_whitelist()

        self.instruments = await self.pantheon.get_instruments_live_source(
            exchanges=["drft"],
            symbols=[],
            kinds=[],
            usage=InstrumentUsageExchanges.TradableOnly,
            lifecycles=[InstrumentLifecycle.ACTIVE],
            rmq_conn_name="url",
        )

        self._clients_pool = ClientsPool(
            pantheon=self.pantheon,
            config=self._config["clients_pool"],
            env=self._config["env"]
            )
        await self._clients_pool.start(secret=secret)

        await self._init_current_slot()

        drift_client = self._clients_pool.get_client()
        self.wallet_public_key = drift_client.wallet.public_key
        self.user_public_key = drift_client.get_user().user_public_key

        if self.dex_access_mode == AccessMode.READWRITE:
            self.keypair = drift_client.wallet.payer

        self._logger.info(f"User public key is : {str(self.user_public_key)}")

        self._order_cache.start()

        if self._makers is not None:
            await self._makers.start(self._clients_pool)

        if self._config["event_subscribers"]["enabled"]:
            self._event_subscribers = EventSubscribers(
                pantheon=self.pantheon,
                config=self._config["event_subscribers"],
                env=self._config["env"],
                user_public_key=self.user_public_key,
                order_cache=self._order_cache,
                dex=self,
            )
            await self._event_subscribers.start()

        if self.dex_access_mode == AccessMode.READWRITE:
            self._rest_order_poller = RestOrderStatusSyncer(
                pantheon=self.pantheon,
                config=self._config["rest_order_poller"],
                user_public_key=str(self.user_public_key),
                order_cache=self._order_cache,
                dex=self,
            )
            self._logger.info("Spawning rest order poller")
            self._rest_order_poller.start()

        self.pantheon.spawn(self._update_markets())
        if self.dex_access_mode == AccessMode.READWRITE:
            self.pantheon.spawn(self._settle_pnl_loop())

        self.started = True

    async def _init_current_slot(self):
        while True:
            try:
                current_slot = await self._clients_pool.get_current_slot()

                if current_slot:
                    self._current_slot = current_slot
                    self._logger.info(f"Initialised current slot {self._current_slot}")
                    return
                else:
                    self._logger.error("Failed to set current slot will retry after 1s.")
            except Exception as ex:
                self._logger.exception(
                    f"Error setting current slot. Will retry after 1s. %r", ex
                )

            await self.pantheon.sleep(1)

    async def _settle_pnl_loop(self):
        while True:
            try:
                self._logger.info("Starting Settlement loop")
                self._logger.info(
                    f"Sleeping for {self.perp_pnl_settlement_frequency} seconds"
                )
                await self.pantheon.sleep(self.perp_pnl_settlement_frequency)
                self._logger.info("Woke up, settling PnL")
                await self._settle_pnl()
            except Exception as e:
                self._logger.exception(f"settle pnl failed: %r", e)

    async def _settle_pnl(self):
        drift_client = self._clients_pool.get_client()
        drift_user = drift_client.get_user()
        tasks = []
        map_market_index_to_name = {
            market.market_index: decode_name(market.name)
            for market in drift_client.get_perp_market_accounts()
        }
        settled_perps = []
        for perp in drift_client.get_perp_market_accounts():
            unrealized_pnl = drift_user.get_unrealized_pnl(
                market_index=perp.market_index, with_funding=True, strict=True
            )
            self._logger.info(
                f"Market {perp.market_index}: Unrealized PnL = {unrealized_pnl}"
            )
            if unrealized_pnl:
                task = drift_client.settle_pnl(
                    self.user_public_key,
                    drift_user.get_user_account(),
                    perp.market_index,
                )
                tasks.append(task)
                settled_perps.append(map_market_index_to_name.get(perp.market_index))
        self._logger.info(f"settled_perps are {settled_perps}")
        if tasks:
            self._logger.info(f"settled pnl at {datetime.now()} in {settled_perps}")
            await asyncio.gather(*tasks)

    async def _update_markets(self) -> None:
        while True:
            try:
                drift_client = self._clients_pool.get_client()
                all_spot_markets = await drift_client.program.account["SpotMarket"].all()
                all_spot_markets = {
                    x.account.market_index: bytes(x.account.name).decode("utf-8").strip()
                    for x in all_spot_markets
                }
                self._spot_id2name = all_spot_markets
                self._spot_name2id = {
                    name: id for id, name in self._spot_id2name.items()
                }

                all_perp_markets = await drift_client.program.account["PerpMarket"].all()
                all_perp_markets = {
                    x.account.market_index: bytes(x.account.name).decode("utf-8").strip()
                    for x in all_perp_markets
                }
                self._perp_id2name = all_perp_markets
                self._perp_name2id = {
                    name: id for id, name in self._perp_id2name.items()
                }

                self._logger.info(
                    f"updated markets, spot:{self._spot_name2id}, perp:{self._perp_name2id}"
                )
            except Exception as e:
                self._logger.exception(f"updating markets failed: %r", e)

            await self.pantheon.sleep(self._markets_refresh_interval_s)

    def get_instrument_by_native(self, native_code: str):
        return self.instruments.get_instrument_by_native(
            exchange="drft", native_code=native_code
        )

    def _get_drift_order_params(self, order: Order) -> OrderParams:
        if order.drift_market_index is None:
            instrument = self.get_instrument_by_native(order.symbol)

            if not instrument:
                raise ValueError(f"Unknown instrument native code {order.symbol}")

            if instrument.kind == InstrumentKind.SPOT:
                order.drift_market_type = market_type_to_string(DriftMarketType.Spot())
                order.drift_market_index = self._spot_name2id.get(
                    instrument.native_code
                )
                if order.drift_market_index is None:
                    raise ValueError(f"unknown spot market {instrument.native_code}")
                order.price_mult = PRICE_PRECISION
                spot_market = self._clients_pool.get_client().get_spot_market_account(
                    order.drift_market_index
                )
                order.qty_mult = 10**spot_market.decimals
            elif instrument.kind == InstrumentKind.SWAP:
                order.drift_market_type = market_type_to_string(DriftMarketType.Perp())
                order.drift_market_index = self._perp_name2id.get(
                    instrument.native_code
                )
                if order.drift_market_index is None:
                    raise ValueError(f"unknown perp market {instrument.native_code}")
                order.price_mult = PRICE_PRECISION
                order.qty_mult = BASE_PRECISION
            else:
                raise ValueError(f"unknown instrument kind: {instrument.kind}")
        assert (
            order.drift_market_index is not None
            and order.qty_mult > 0
            and order.price_mult > 0
        )

        order_params = OrderParams(
            order_type=DriftOrderType.Limit(),  # Market or Limit or TriggerMarket or TriggerLimit or Oracle
            base_asset_amount=int(order.qty * order.qty_mult),
            market_index=order.drift_market_index,
            direction=(
                PositionDirection.Short()
                if order.side == Side.SELL
                else PositionDirection.Long()
            ),
            price=int(order.price * order.price_mult),
            user_order_id=order.drift_user_order_id,
            market_type=get_drift_market_type(order.drift_market_type),
        )

        if order.order_type == OrderType.GTC_POST_ONLY:
            order_params.post_only = PostOnlyParams.MustPostOnly()
        elif order.order_type == OrderType.IOC:
            order_params.bit_flags |= OrderParamsBitFlag.IMMEDIATE_OR_CANCEL

        return order_params

    async def _initialize_user(
        self, path: str, params: dict, received_at_ms: int
    ) -> Tuple[int, dict]:
        drift_client = self._clients_pool.get_client()
        response = {
            "account": self._account,
            "subaccount": drift_client.active_sub_account_id,
        }
        try:
            tx_sig = await drift_client.initialize_user(
                name=self._account,
                sub_account_id=drift_client.active_sub_account_id,
            )
            response["tx_sig"] = str(tx_sig)
            self._logger.info(f"initialized {response}")
            return 200, response
        except Exception as e:
            if "already in use" in str(e):
                self._logger.debug(f"{response} already initialized")
                return 200, response
            else:
                response["failure"] = str(e)
                self._logger.error(f"failed to initialize {response}")
                return 400, response

    async def _update_margin_trading(self, enabled: bool) -> Tuple[int, dict]:
        drift_client = self._clients_pool.get_client()
        response = {
            "account": self._account,
            "subaccount": drift_client.active_sub_account_id,
        }
        try:
            tx_sig = await drift_client.update_user_margin_trading_enabled(
                margin_trading_enabled=enabled,
                sub_account_id=drift_client.active_sub_account_id,
            )
            response["enabled"] = enabled
            response["tx_sig"] = str(tx_sig)
            self._logger.info(f"margin trading update succeeded: {response}")
            return 200, response
        except Exception as e:
            response["failure"] = str(e)
            self._logger.error(f"margin trading update failed: {response}")
            return 400, response

    async def _enable_margin_trading(
        self, path: str, params: dict, received_at_ms: int
    ) -> Tuple[int, dict]:
        return await self._update_margin_trading(True)

    async def _disable_margin_trading(
        self, path: str, params: dict, received_at_ms: int
    ) -> Tuple[int, dict]:
        return await self._update_margin_trading(False)

    async def _place_order(self, order: Order):
        order_params = self._get_drift_order_params(order)
        self._order_cache.add_or_update(order)
        self._logger.info(f"sending order_params: {order_params}")

        drift_client_name = self._clients_pool.get_leading_client_name()
        drift_client = self._clients_pool.get_client_by_name(drift_client_name)

        makers = None
        if OrderParamsBitFlag.is_immediate_or_cancel(order_params.bit_flags):
            if self._makers is None:
                raise Exception(
                    "IOC orders not supported because makers getter is not configured"
                )
            makers = await self._makers.get_makers(
                drift_client_name,
                drift_client.program_id,
                order_params.market_type,
                order_params.market_index,
                order_params.direction,
                order.price_mult,
                order.qty_mult)
            if makers is None or len(makers) == 0:
                raise Exception("No makers found")

        if order_params.market_type == DriftMarketType.Perp():
            if makers is None:
                tx_sig = await drift_client.place_perp_order(order_params)
            else:
                tx_sig = await drift_client.place_and_take_perp_order(
                    order_params=order_params,
                    maker_info=makers
                )

            self.__update_and_get_current_slot(
                drift_client.last_perp_market_seen_cache.get(
                    order_params.market_index, None
                )
            )

        elif order_params.market_type == DriftMarketType.Spot():
            if makers is None:
                tx_sig = await drift_client.place_spot_order(order_params)
            else:
                tx_sig = await drift_client.place_and_take_spot_order(
                    order_params=order_params,
                    maker_info=makers
                )

            self.__update_and_get_current_slot(
                drift_client.last_spot_market_seen_cache.get(
                    order_params.market_index, None
                )
            )

        else:
            raise Exception(f"Unknown market type {order_params.market_type}")

        return tx_sig

    async def _create_order(
        self, path: str, params: dict, received_at_ms: int
    ) -> Tuple[int, dict]:
        if (
            self._order_cache.total_drift_user_order_id_in_use()
            >= MAX_DRIFT_USER_ORDER_ID
        ):
            return 400, {
                "error_code": "TRADING_RULES_BREACH",
                "error_message": f"maximum of {MAX_DRIFT_USER_ORDER_ID} active orders reached",
            }

        try:
            price = Decimal(params["price"])
        except:
            raise ValueError("price is not a number")
        if price <= 0.0:
            raise ValueError("price must be positive")

        try:
            qty = Decimal(params["quantity"])
        except:
            raise ValueError("quantity is not a number")
        if qty <= 0.0:
            raise ValueError("quantity must be positive")

        client_order_id = int(params["client_order_id"])
        if self._order_cache.is_auros_order_id_in_use(client_order_id):
            raise ValueError(f"client order id {client_order_id} already exists")

        drift_user_order_id = 0
        for _ in range(MAX_DRIFT_USER_ORDER_ID):
            dcoid = self._get_next_drift_user_order_id()
            if not self._order_cache.is_drift_user_order_id_in_use(dcoid):
                drift_user_order_id = dcoid
                break

        assert (
            0 < drift_user_order_id and drift_user_order_id <= MAX_DRIFT_USER_ORDER_ID
        )

        order = Order(
            received_at=TimestampNs.from_ns_since_epoch(received_at_ms * 1000_000),
            auros_order_id=client_order_id,
            drift_user_order_id=drift_user_order_id,
            drift_order_id=None,
            price=price,
            qty=qty,
            side=Side[params["side"]],
            order_type=OrderType[params["order_type"]],
            symbol=str(params["symbol"]),
            slot=self.__update_and_get_current_slot(),
        )

        try:
            tx_sig = await self._place_order(order)
            order.place_tx_sig = str(tx_sig)
        except Exception as ex:
            self._logger.exception(
                f"Exception while inserting order {client_order_id}. %r", ex
            )
            error_code = classify_insert_error(str(ex))

            if error_code == "TRANSPORT_FAILURE":
                # RestOrderStatusSyncer will handle finalising of this order if required
                pass
            else:
                order.status = OrderStatus.REJECTED
                order.reason = error_code
                self._order_cache.on_finalised(order.auros_order_id)

            return 400, {
                "error_code": error_code,
                "error_message": f"failed to insert order {client_order_id}. Reason: {ex}",
            }

        response = order_to_dict(order)
        response["send_timestamp_ns"] = TimestampNs.now().get_ns_since_epoch()

        self._logger.info(f"created order: {full_order_to_dict(order)}")
        return 200, response

    async def _cancel_order(
        self, path: str, params: dict, received_at_ms: int
    ) -> Tuple[int, dict]:
        auros_order_id = int(params["client_order_id"])

        order = self._order_cache.get_order_from_auros_order_id(auros_order_id)
        if not order:
            return 404, {
                "error_code": "ORDER_NOT_FOUND",
                "error_message": f"order {auros_order_id} not found",
            }

        if order.is_finalised():
            response = order_to_dict(order)
            response["send_timestamp_ns"] = TimestampNs.now().get_ns_since_epoch()
            return 200, response

        tx_sig = None

        try:
            drift_client = self._clients_pool.get_client()
            tx_sig = await drift_client.cancel_order_by_user_id(
                order.drift_user_order_id
            )
        except Exception as ex:
            error_msg = str(ex)

            if should_send_cancel_order_error(error_msg):
                return 400, {
                    "error_code": classify_cancel_error(error_msg),
                    "error_message": f"failed to cancel order {auros_order_id}. Reason: {ex}",
                }

        response = order_to_dict(order)
        response["send_timestamp_ns"] = TimestampNs.now().get_ns_since_epoch()

        if tx_sig:
            response["tx_sig"] = str(tx_sig)
            self._logger.info(f"canceled order: {full_order_to_dict(order)}")

        return 200, response

    async def _query_order(
        self, path: str, params: dict, received_at_ms: int
    ) -> Tuple[int, dict]:
        auros_order_id = int(params["client_order_id"])

        order = self._order_cache.get_order_from_auros_order_id(auros_order_id)
        if not order:
            return 404, {
                "error_code": "ORDER_NOT_FOUND",
                "error_message": f"order {auros_order_id} not found",
            }

        # maybe do this, and store nothing (regarding orders) in the cache here ?
        # drift_user = self._clients_pool.get_client().get_user()
        # drift_order = self._drift_user.get_order_by_user_order_id(order_id)
        # self._update_order(drift_order)

        response = order_to_dict(order)
        response["send_timestamp_ns"] = TimestampNs.now().get_ns_since_epoch()
        return 200, response

    async def _query_live_orders(
        self, path: str, params: dict, received_at_ms: int
    ) -> Tuple[int, dict]:
        response = {}
        response["send_timestamp_ns"] = TimestampNs.now().get_ns_since_epoch()
        response["orders"] = [
            order_to_dict(order) for order in self._order_cache.get_all_open_orders()
        ]
        return 200, response

    async def _query_portfolio(
        self, path: str, params: dict, received_at_ms: int
    ) -> Tuple[int, dict]:
        response = {}
        try:
            drift_client, drift_user = self.__get_drift_client_user_from_params(params)
        except Exception as e:
            return 400, {"error": str(e)}
        response["send_timestamp_ns"] = TimestampNs.now().get_ns_since_epoch()
        response["spot_positions"] = self.__get_spot_positions(drift_client, drift_user)
        response["perp_positions"] = self.__get_perp_positions(drift_client, drift_user)
        return 200, response

    def __get_spot_positions(self, drift_client, drift_user) -> Dict[str, float]:
        user_account = drift_user.get_user_account()
        positions = {}
        for position in user_account.spot_positions:
            if position.scaled_balance == 0:
                continue
            spot = drift_client.get_spot_market_account(position.market_index)
            name = decode_name(spot.name)
            balance = convert_to_number(drift_user.get_token_amount(spot.market_index), pow(10, spot.decimals))
            positions[name] = balance
        return positions

    def __get_perp_positions(self, drift_client, drift_user) -> Dict[str, float]:
        user_account = drift_user.get_user_account()
        positions = {}
        for position in user_account.perp_positions:
            if position.base_asset_amount == 0:
                continue
            perp = drift_client.get_perp_market_account(position.market_index)
            name = decode_name(perp.name)
            position = convert_to_number(position.base_asset_amount, BASE_PRECISION)
            positions[name] = position
        return positions

    async def _cancel_all_orders(
        self, path: str, params: dict, received_at_ms: int
    ) -> Tuple[int, dict]:
        tx_sig = None
        try:
            drift_client = self._clients_pool.get_client()
            tx_sig = await drift_client.cancel_orders()
            self._logger.info(f"cancel all orders tx_sig: {tx_sig}")
        except Exception as e:
            self._logger.exception(f"canceling all orders failed: %r", e)

        cancelled = []

        for order in self._order_cache.get_all_open_orders():
            if order.order_type != OrderType.IOC:
                cancelled.append(order.auros_order_id)
                order.last_update = TimestampNs.now()

        return 200, {
            "cancelled": cancelled,
            "send_timestamp_ns": TimestampNs.now().get_ns_since_epoch(),
        }

    async def on_new_connection(self, ws):
        self._logger.info(f"new connection {ws}")

    async def process_request(self, ws, request_id, method, params: dict):
        pass

    async def _approve(self, request, gas_price_wei, nonce=None):
        pass

    async def _amend_transaction(self, request, params, gas_price_wei):
        pass

    async def _cancel_transaction(self, request, gas_price_wei):
        pass

    async def get_transaction_receipt(self, request, tx_hash):
        pass

    def _get_gas_price(self, request, priority_fee: Any):
        pass

    async def on_request_status_update(
        self,
        client_request_id,
        request_status,
        tx_receipt: dict,
        mined_tx_hash: str = None,
    ):
        await super().on_request_status_update(
            client_request_id, request_status, tx_receipt, mined_tx_hash
        )

    async def _get_all_open_requests(
        self, path: str, params: dict, received_at_ms: int
    ):
        pass

    async def _cancel_all(self, path: str, params: dict, received_at_ms: int):
        pass

    def __parse_subaccount_id(self, params: dict) -> int:
        subaccount_param = params.get('subaccount_id') if params else None
        if subaccount_param is None:
            return DEFAULT_SUB_ACCOUNT_ID
        return int(subaccount_param)

    def __get_drift_client_user_from_params(self, params: dict) -> tuple[DriftClient, DriftUser]:
        drift_client = self._clients_pool.get_client()
        # Parse and validate subaccount id
        try:
            subaccount_param = params.get('subaccount_id') if params else None
            subaccount_id = int(subaccount_param) if subaccount_param is not None else DEFAULT_SUB_ACCOUNT_ID
        except Exception:
            raise ValueError(f"INVALID_SUBACCOUNT_ID: must be an integer; got={params.get('subaccount_id')}")

        # Membership validation against configured sub accounts
        configured = getattr(drift_client, 'sub_account_ids', None)
        if configured is not None and subaccount_id not in configured:
            raise ValueError(
                f"SUBACCOUNT_NOT_SUBSCRIBED: subaccount_id={subaccount_id} not in configured={configured}"
            )

        # Resolve user, map common driftpy errors to clearer codes
        try:
            user = drift_client.get_user(subaccount_id)
        except Exception as ex:
            msg = str(ex)
            if "No sub account id" in msg or "No subaccount" in msg or "not found" in msg:
                raise ValueError(
                    f"SUBACCOUNT_NOT_INITIALIZED: subaccount_id={subaccount_id} not initialized on-chain"
                )
            raise ValueError(f"USER_RESOLVE_FAILED: {msg}")

        return drift_client, user

    def __fetch_market_index_from_token_name(self, token_name: str, drift_client: DriftClient):
        map_token_name_to_marker_index = {
            decode_name(market.name): market.market_index
            for market in drift_client.get_spot_market_accounts()
        }
        return map_token_name_to_marker_index.get(token_name)

    async def _deposit(self, path: str, params: dict, received_at_ms: int):
        token = params["token"]
        amount = float(params["amount"])

        drift_client = self._clients_pool.get_client()
        spot_market_index = self.__fetch_market_index_from_token_name(token_name=token, drift_client=drift_client)

        if spot_market_index is None:
            return 400, {"error": "Invalid token"}

        amount = drift_client.convert_to_spot_precision(amount, spot_market_index)
        user_token_account = drift_client.get_associated_token_account_public_key(
            spot_market_index
        )
        tx_sig = None
        if token == "SOL":
            tx_sig = await drift_client.deposit(amount, spot_market_index, self.wallet_public_key)
        else:
            tx_sig = await drift_client.deposit(
                amount, spot_market_index, user_token_account
            )
        self._logger.debug(f"[deposit] tx_sig: {tx_sig.tx_sig}")

        if tx_sig is None:
            return 500, {"status": "Transaction failed"}
        return 200, {"tx_sig": str(tx_sig.tx_sig)}

    async def _withdraw(self, path: str, params: dict, received_at_ms: int):
        token = params["token"]
        amount = float(params["amount"])
        drift_client = self._clients_pool.get_client()
        spot_market_index = self.__fetch_market_index_from_token_name(token_name=token, drift_client=drift_client)
        if spot_market_index is None:
            return 400, {"error": "Invalid token"}

        amount = drift_client.convert_to_spot_precision(amount, spot_market_index)

        if token == "SOL":
            tx_sig = await drift_client.withdraw(amount, spot_market_index, self.wallet_public_key)

        else:
            user_token_account = (
                drift_client.get_associated_token_account_public_key(
                    spot_market_index
                )
            )

            tx_sig = await drift_client.withdraw(
                amount, spot_market_index, user_token_account
            )

        self._logger.debug(f"[withdraw] tx_sig: {tx_sig.tx_sig}")
        return 200, {"tx_sig": str(tx_sig.tx_sig)}

    async def _get_balance(self, path: str, params: dict, received_at_ms: int):
        try:
            drift_client, drift_user = self.__get_drift_client_user_from_params(params)
        except Exception as e:
            return 400, {"error": str(e)}
        spot_market_accounts = await drift_client.program.account["SpotMarket"].all()
        result = []
        perp_pnl = drift_user.get_unrealized_pnl(with_funding=False)
        for market_account in spot_market_accounts:
            market = market_account.account
            balance = drift_user.get_token_amount(market.market_index)
            resp = {
                "symbol": bytes(market.name).decode("utf-8").strip(),
                "mint": str(market.mint),
                "decimals": market.decimals,
                "status": self._get_market_status_name(market.status),
                "balance": balance,
            }
            result.append(resp)

        return 200, {"success": True, "perp_pnl": perp_pnl, "balances": result}

    async def _get_user_info(self, path: str, params: dict, received_at_ms: int):
        try:
            drift_client, drift_user = self.__get_drift_client_user_from_params(params)
        except Exception as e:
            return 400, {"error": str(e)}

        subaccount_id = self.__parse_subaccount_id(params)
        info = {
            "wallet_public_key": str(drift_client.wallet.public_key),
            "user_public_key": str(drift_user.user_public_key),
            "subaccount_id": subaccount_id,
            "associated_token_accounts": [],
        }

        try:
            spot_market_accounts = await drift_client.program.account["SpotMarket"].all()
            for market_account in spot_market_accounts:
                market = market_account.account
                try:
                    ata = str(drift_client.get_associated_token_account_public_key(market.market_index))
                except Exception:
                    ata = None
                info["associated_token_accounts"].append({
                    "symbol": bytes(market.name).decode("utf-8").strip(),
                    "market_index": market.market_index,
                    "ata": ata,
                })
        except Exception as e:
            self._logger.warning("Failed to enumerate ATAs: %s", e)

        return 200, info

    async def _make_api_request(self, path: str, params: dict = None) -> Optional[dict]:
        """
        Make a reusable API request to the configured Drift API endpoint.

        Args:
            path: API endpoint path (e.g., "/contracts", "/user/{user_id}/trades")
            params: Optional query parameters as a dictionary

        Returns:
            JSON response data or None if request fails
        """
        try:
            # Build the full URL
            url = f"{self._api_base_url}{path}"

            # Add query parameters if provided
            if params:
                query_string = "&".join([f"{k}={v}" for k, v in params.items() if v is not None])
                if query_string:
                    url += f"?{query_string}"

            # Prepare headers
            headers = {}
            if self._api_key:
                headers["X-API-Key"] = self._api_key

            timeout = aiohttp.ClientTimeout(total=self._api_timeout_s)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers) as response:
                    response.raise_for_status()
                    data = await response.json()
                    return data
        except Exception as e:
            self._logger.error(f"[ERROR] API request failed for path '{path}': {e}")
            return None

    async def __get_drift_contracts(self) -> Optional[dict]:
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(
                    "https://data.api.drift.trade/contracts"
                ) as response:
                    response.raise_for_status()
                    data = await response.json()
                    return data
        except Exception as e:
            self._logger.error(f"[ERROR] Exception occurred: {e}")
            return None

    async def _get_contract_data(self, path: str, params: dict, received_at_ms: int):
        contract_data = {}
        contract_data_response = await self.__get_drift_contracts()
        if contract_data_response is None:
            return 500, {"error": "Failed to retrieve contract data"}

        markets = []
        try:
            drift_client, drift_user = self.__get_drift_client_user_from_params(params)
        except Exception as e:
            return 400, {"error": str(e)}
        for contract in contract_data_response.get("contracts", []):
            amm = None
            mark_price = None
            perp_market = drift_user.get_perp_market_account(contract["contract_index"])

            if perp_market:
                amm = perp_market.amm
            if amm:
                try:
                    oracle_price_data = (
                        drift_client.get_oracle_price_data_for_perp_market(
                            contract["contract_index"]
                        )
                    )
                    bid, ask = calculate_bid_ask_price(
                        amm, oracle_price_data, with_update=False
                    )
                    self._logger.debug(f"{contract['ticker_id']} {bid} {ask}")
                    mark_price = (bid + ask) / 2
                except Exception:
                    continue

            contract_data[contract["ticker_id"]] = {
                "next_funding_rate": contract["next_funding_rate"],
                "next_funding_rate_timestamp": contract["next_funding_rate_timestamp"],
                "funding_rate": contract["funding_rate"],
                "open_interest": contract["open_interest"],
                "index_price": contract["index_price"],
                "mark_price": mark_price / PRICE_PRECISION if mark_price else "N/A",
            }
            markets.append(contract["ticker_id"])

        return 200, contract_data

    async def _get_margin_data(self, path: str, params: dict, received_at_ms: int):
        try:
            drift_client, drift_user = self.__get_drift_client_user_from_params(params)
        except Exception as e:
            return 400, {"error": str(e)}
        user_account = drift_user.get_user_account()

        total_collateral = drift_user.get_total_collateral(
            MarginCategory.MAINTENANCE
        )

        maintenance_margin = drift_user.get_margin_requirement(
            MarginCategory.MAINTENANCE
        )

        maintenance_ratio = (
            (total_collateral / maintenance_margin)
            if maintenance_margin > 0
            else MAX_DUMMY_VALUE
        )
        available_margin = drift_user.get_free_collateral(
            MarginCategory.MAINTENANCE
        )

        upnl = drift_user.get_unrealized_pnl(with_funding=True)

        total_equity = drift_user.get_total_collateral(MarginCategory.MAINTENANCE)

        map_market_index_to_name = {
            market.market_index: decode_name(market.name)
            for market in drift_client.get_perp_market_accounts()
        }

        margin_data = {
            "total_collateral": total_collateral / QUOTE_PRECISION,
            "maintenance_ratio": maintenance_ratio,
            "available_margin": available_margin / MARGIN_PRECISION_OVERRIDE,
            "maintenance_margin": maintenance_margin / MARGIN_PRECISION_OVERRIDE,
            "total_equity": total_equity / QUOTE_PRECISION,
            "upnl": upnl / PRICE_PRECISION,
            "perp_positions": [
                {
                    "market_index": pos.market_index,
                    "name": map_market_index_to_name[pos.market_index],
                    "size": pos.base_asset_amount / BASE_PRECISION,
                    "entry_price": (pos.quote_entry_amount / pos.base_asset_amount)
                    * 10**3,
                    "pnl": pos.settled_pnl / QUOTE_PRECISION,
                    "market": pos.market_index,
                    "size_usd": (pos.quote_entry_amount) / QUOTE_PRECISION,
                    "unrealized_pnl": drift_user.get_unrealized_pnl(
                        market_index=pos.market_index, with_funding=True, strict=True
                    )
                    / QUOTE_PRECISION,
                }
                for pos in user_account.perp_positions
                if pos.base_asset_amount != 0
            ],
        }

        return 200, margin_data

    def __convert_symbol(self, native_name: str) -> str:
        return native_name.replace("-PERP", "").upper()

    async def _fetch_markets(self, path: str, params: dict, received_at_ms: int):
        drift_client = self._clients_pool.get_client()
        response = []
        for perp_market in drift_client.get_perp_market_accounts():
            response.append(
                {
                    "base": decode_name(perp_market.name),
                    "base_currency": self.__convert_symbol(
                        decode_name(perp_market.name)
                    ),
                    "quote_currency": "USDC",
                    "tick_size": str(
                        Decimal(perp_market.amm.order_tick_size) / QUOTE_PRECISION
                    ),
                    "min_order_size": str(
                        Decimal(perp_market.amm.min_order_size) / BASE_PRECISION
                    ),
                    "step_order_size": str(
                        Decimal(perp_market.amm.order_step_size) / BASE_PRECISION
                    ),
                    "is_active_on_exchange": equal_drift_enum(
                        perp_market.status, MarketStatus.Active()
                    ),
                    "raw_response": str(perp_market),
                    "custom_fields": {
                        "baseDecimals": BASE_PRECISION,
                        "quoteDecimals": QUOTE_PRECISION,
                        "nativeIndex": perp_market.market_index,
                    },
                }
            )

        return 200, {"data": response}

    async def _fetch_transfer_records(
        self, path: str, params: dict, received_at_ms: int
    ):
        next_page = params.get("next_page")
        try:
            _, drift_user = self.__get_drift_client_user_from_params(params)
            user_public_key = str(drift_user.user_public_key)
        except Exception as e:
            return 400, {"error": str(e)}

        api_params = {"page": next_page} if next_page else None
        data = await self._make_api_request(f"/user/{user_public_key}/deposits", api_params)

        if data is None:
            return 500, {"error": "Failed to retrieve transfers"}

        return 200, data

    async def _fetch_funding_records(
        self, path: str, params: dict, received_at_ms: int
    ):
        try:
            drift_client, drift_user = self.__get_drift_client_user_from_params(params)
            user_public_key = str(drift_user.user_public_key)
        except Exception as e:
            return 400, {"error": str(e)}
        next_page = params.get("next_page")
        map_market_index_to_name = {
            market.market_index: decode_name(market.name)
            for market in drift_client.get_perp_market_accounts()
        }

        api_params = {"page": next_page} if next_page else None
        data = await self._make_api_request(f"/user/{user_public_key}/fundingPayments", api_params)

        if data is None:
            return 500, {"error": "Failed to retrieve funding records"}

        # Process the data to add native codes
        for datum in data["records"]:
            datum["nativeCode"] = map_market_index_to_name[datum["marketIndex"]]

        return 200, data

    async def _fetch_trades(self, path: str, params: dict, received_at_ms: int):
        next_page = params.get("next_page")
        try:
            _, drift_user = self.__get_drift_client_user_from_params(params)
            user_public_key = str(drift_user.user_public_key)
        except Exception as e:
            return 400, {"error": str(e)}

        api_params = {"page": next_page} if next_page else None
        data = await self._make_api_request(f"/user/{user_public_key}/trades", api_params)

        if data is None:
            return 500, {"error": "Failed to retrieve trades"}

        return 200, data

    async def _transfer(self, request, gas_price_wei: int, nonce: int = None):
        try:
            token, destination, amount, gas_limit, client_request_id = (
                request.symbol,
                request.address_to,
                Decimal(request.amount),
                request.gas_limit,
                request.client_request_id,
            )

            if not self._is_withdraw_allowed(client_request_id, token, destination):
                self._request_cache.finalise_request(
                    client_request_id, RequestStatus.FAILED
                )
                return self.__tx_result_error(
                    "withdraw_not_allowed", ErrorType.TRANSACTION_FAILED
                )

            mint_info = self._withdrawal_address_whitelists[token]
            mint = Pubkey.from_string(mint_info["mint"])
            decimals = mint_info["decimals"]
            amount = int(amount * (10**decimals))

            blockhash = self._get_latest_blockhash()
            if not blockhash:
                self._request_cache.finalise_request(
                    client_request_id, RequestStatus.FAILED
                )
                return self.__tx_result_error(
                    "blockhash_error", ErrorType.TRANSACTION_FAILED
                )

            spl_client = Token(
                conn=self.solana_client,
                pubkey=mint,
                program_id=TOKEN_PROGRAM_ID,
                payer=self.keypair,
            )

            source = self.keypair.pubkey()
            dest = Pubkey.from_string(destination)
            source_token_account = self.__get_or_create_token_account(
                spl_client, source, blockhash
            )
            dest_token_account = self.__get_or_create_token_account(
                spl_client, dest, blockhash
            )

            if not self.__is_valid_account(
                spl_client, source_token_account, check_balance=True
            ):
                self._request_cache.finalise_request(
                    client_request_id, RequestStatus.FAILED
                )
                return self.__tx_result_error(
                    "invalid_source_account", ErrorType.TRANSACTION_FAILED
                )

            if not self.__is_valid_account(spl_client, dest_token_account):
                self._request_cache.finalise_request(
                    client_request_id, RequestStatus.FAILED
                )
                return self.__tx_result_error(
                    "invalid_destination_account", ErrorType.TRANSACTION_FAILED
                )

            transfer_ix = transfer(
                TransferParams(
                    program_id=TOKEN_PROGRAM_ID,
                    source=source_token_account,
                    dest=dest_token_account,
                    owner=source,
                    amount=amount,
                    signers=[],
                )
            )

            message = Message.new_with_blockhash([transfer_ix], source, blockhash)
            versioned_txn = VersionedTransaction(message, [self.keypair])

            fee_info = self.solana_client.get_fee_for_message(message)
            if fee_info.value > gas_limit:
                self._request_cache.finalise_request(
                    client_request_id, RequestStatus.FAILED
                )
                return self.__tx_result_error(
                    "fee_exceeds_gas_limit", ErrorType.TRANSACTION_FAILED
                )

            txid = self.solana_client.send_transaction(versioned_txn)
            self._request_cache.finalise_request(
                client_request_id, RequestStatus.SUCCEEDED
            )
            return self.__tx_result_success(str(blockhash), txid)

        except Exception as e:
            self._logger.error(f"transfer_error : {str(e)}", exc_info=True)
            self._request_cache.finalise_request(
                client_request_id, RequestStatus.FAILED
            )
            return self.__tx_result_error(
                f"transfer_error: {str(e)}", ErrorType.TRANSACTION_FAILED
            )

    def _is_withdraw_allowed(self, client_request_id, token, destination):
        allow, _ = self._allow_withdraw(client_request_id, token, destination)
        return allow

    def _get_latest_blockhash(self):
        try:
            return self.solana_client.get_latest_blockhash().value.blockhash
        except:
            return None

    def __get_or_create_token_account(self, spl_client, owner, blockhash):
        accounts = spl_client.get_accounts_by_owner(owner=owner, commitment="confirmed")
        if accounts.value:
            return accounts.value[0].pubkey
        return spl_client.create_associated_token_account(
            owner=owner,
            skip_confirmation=True,
            recent_blockhash=blockhash,
        )

    def __is_valid_account(self, spl_client, account_pubkey, check_balance=False):
        info = spl_client.get_account_info(account_pubkey)
        if not info:
            return False
        if check_balance and not info.amount:
            return False
        return True

    def __extract_tx_hash(self, tx_success_response_str):
        match = re.search(r"Signature\((.*?)\)", tx_success_response_str)
        if match:
            hash_value = match.group(1)
            return hash_value
        else:
            raise ValueError("No signature hash found in the input string.")

    def __tx_result_success(self, nonce, tx_hash):
        return ApiResult(
            nonce=nonce,
            tx_hash=self.__extract_tx_hash(str(tx_hash)),
            error_type=ErrorType.NO_ERROR,
            pending_task=None,
        )

    def __tx_result_error(self, error, error_type):
        return ApiResult(error=error, error_type=error_type, pending_task=None)

    def _allow_withdraw(self, client_request_id, token, destination):
        if token not in self._withdrawal_address_whitelists:
            self._logger.error(
                f"HIGH ALERT: client_request_id={client_request_id} tried to withdraw unknown token={token}"
            )
            return False, f"Unknown token={token}"

        assert destination is not None

        if (
            destination
            not in self._withdrawal_address_whitelists[token][
                "valid_withdrawal_addresses"
            ]
        ):
            self._logger.error(
                f"HIGH ALERT: client_request_id={client_request_id} tried to withdraw token={token} "
                f"to unknown address={destination}"
            )
            return False, f"Unknown withdrawal_address={destination} for token={token}"

        return True, ""

    async def _send_order_update(self, auros_order_id: int):
        order = self._order_cache.get_order_from_auros_order_id(auros_order_id)

        if order:
            channel = "ORDER"
            event = {
                "jsonrpc": "2.0",
                "method": "subscription",
                "params": {
                    "channel": channel,
                    "send_timestamp_ns": TimestampNs.now().get_ns_since_epoch(),
                    "data": order_to_dict(order),
                },
            }
            await self._event_sink.on_event(channel, event)
        else:
            self._logger.warning(
                f"Order cleared before sending update to the client, client_order_id={auros_order_id}"
            )

    def _get_next_drift_user_order_id(self) -> int:
        res = self._next_drift_user_order_id
        self._next_drift_user_order_id = (
            self._next_drift_user_order_id % MAX_DRIFT_USER_ORDER_ID
        ) + 1
        return res

    # this method tries to return as latest processed Solana slot as possible
    # the returned slot will be less than or equal to the actual on-chain slot
    def __update_and_get_current_slot(self, slot: int = None) -> int:
        if slot:
            self._current_slot = max(self._current_slot, slot)

        drift_user = self._clients_pool.get_client().get_user()
        data_and_slot = drift_user.get_user_account_and_slot()
        if data_and_slot:
            self._current_slot = max(self._current_slot, data_and_slot.slot)

        return self._current_slot
