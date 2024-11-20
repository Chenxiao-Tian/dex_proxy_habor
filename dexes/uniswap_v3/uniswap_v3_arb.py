import asyncio
import json
import time
import os
from decimal import Decimal
from pantheon import Pantheon
from pantheon.market_data_types import Side
from pantheon.instruments_source import InstrumentLifecycle, InstrumentsLiveSource, InstrumentUsageExchanges
from pantheon.market_data_types import InstrumentId

from pyutils.exchange_apis.uniswapV3_api import *
from pyutils.exchange_apis.erc20web3_api import ErrorType
from pyutils.exchange_connectors import ConnectorType
from pyutils.gas_pricing.eth import PriorityFee

from ..dex_common import DexCommon


class OrderInfo:
    def __init__(self, gas_price_wei: int, base_ccy_qty: Decimal, quote_ccy_qty: Decimal):
        self.gas_price_wei = gas_price_wei
        self.base_ccy_qty = base_ccy_qty
        self.quote_ccy_qty = quote_ccy_qty


class UniswapV3Arb(DexCommon):
    CHANNELS = ['ORDER']

    def __init__(self, pantheon: Pantheon, config, server, event_sink):
        super().__init__(pantheon, ConnectorType.UniswapV3Arb, config, server, event_sink)
        self.msg_queue = asyncio.Queue()

        self._server.register('POST', '/private/insert-order', self.__insert_order)

        self.__instruments: InstrumentsLiveSource = None
        self.__exchange_name = "chainArb-uni3"
        self.__chain_name = config["chain_name"]
        self.__native_token = "ETH"
        self.__contract_addresses_file_path = "/../../resources/uni3_arb_contracts_address.json"
        self.__txn_gas_limit = 1000000

        # 0.01 GWEI usually.
        self.__base_block_gas_price = 10_000_000_000
        self.__tx_hash_to_order_info: Dict[str, OrderInfo] = {}

    def __split_symbol_to_base_quote_ccy(self, symbol):
        instrument = self.__instruments.get_instrument(
            InstrumentId(self.__exchange_name, symbol))
        return instrument.base_currency, instrument.quote_currency, instrument

    async def __send_order_on_chain(self, request: OrderRequest, gas_price_wei: int) -> ApiResult:
        """
            Sends transaction to chain for given client_request_id
        """
        base_ccy_symbol, quote_ccy_symbol, _ = self.__split_symbol_to_base_quote_ccy(request.symbol)
        side = request.side
        client_request_id = request.client_request_id
        try:
            nonce = await self._api.get_next_nonce_to_use()
            request.nonce = nonce
            self._logger.debug(f"Fetched Nonce :{nonce}, Client Request Id: {client_request_id}")
            if side == Side.BUY:
                result = await self._api.swap_exact_output_single(
                    token_in_symbol=quote_ccy_symbol, token_out_symbol=base_ccy_symbol,
                    token_in_max_amount=request.quote_ccy_qty,
                    token_out_amount=request.base_ccy_qty, fee=request.fee_rate,
                    deadline=request.deadline_since_epoch_s,
                    gas_limit=request.gas_limit, gas_price=gas_price_wei, nonce=nonce)
            else:
                result = await self._api.swap_exact_input_single(
                    token_in_symbol=base_ccy_symbol, token_out_symbol=quote_ccy_symbol,
                    token_in_amount=request.base_ccy_qty,
                    token_out_min_amount=request.quote_ccy_qty, fee=request.fee_rate,
                    deadline=request.deadline_since_epoch_s,
                    gas_limit=request.gas_limit, gas_price=gas_price_wei, nonce=nonce)
            if result.error_type == ErrorType.NO_ERROR:
                self._api.update_next_nonce_to_use(nonce+1)
        finally:
            self._api.nonce_lock_release()

        return result

    def __parse_params_to_order(self, params: dict, received_at_ms: int) -> OrderRequest:
        """
            Parse params to construct OrderRequest obj
        """
        client_request_id = params['client_request_id']
        symbol = params['symbol']
        base_ccy_qty = Decimal(params['base_ccy_qty'])
        quote_ccy_qty = Decimal(params['quote_ccy_qty'])
        assert params['side'] == 'BUY' or params['side'] == 'SELL', 'Unknown order side'
        side = Side.BUY if params['side'] == 'BUY' else Side.SELL
        fee_rate = int(params['fee_rate'])
        gas_limit = self.__txn_gas_limit
        timeout_s = int(time.time() + params['timeout_s'])
        order = OrderRequest(client_request_id, symbol, base_ccy_qty,
                             quote_ccy_qty, side, fee_rate, gas_limit, timeout_s, received_at_ms)
        return order

    async def __insert_order(self, path, params: dict, received_at_ms):
        client_request_id = ''
        try:
            client_request_id = params['client_request_id']
            gas_price_wei = int(params['gas_price_wei'])
            if self._request_cache.get(client_request_id) is not None:
                return 400, {'error': {'message': f'client_request_id={client_request_id} is already known'}}
            order = self.__parse_params_to_order(params, received_at_ms)
            base_ccy_symbol, quote_ccy_symbol, instrument = self.__split_symbol_to_base_quote_ccy(order.symbol)
            self._logger.debug(f'Inserting={order}, gas_price_wei={gas_price_wei}')
            self._request_cache.add(order)

            ok, reason = self._check_max_allowed_gas_price(gas_price_wei)
            if not ok:
                self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
                return 400, {'error': {'message': reason}}

            if not self.__validate_tokens_address(instrument.native_code, base_ccy_symbol, quote_ccy_symbol):
                self._request_cache.finalise_request(
                    client_request_id, RequestStatus.FAILED)
                return 400, {'error': {'message': 'unexpected instrument native code'}}

            result = await self.__send_order_on_chain(order, gas_price_wei)
            if result.error_type == ErrorType.NO_ERROR:
                order.order_id = result.tx_hash
                order.nonce = result.nonce
                order.tx_hashes.append((result.tx_hash, RequestType.ORDER.name))
                order.used_gas_prices_wei.append(gas_price_wei)

                self._transactions_status_poller.add_for_polling(result.tx_hash, client_request_id, RequestType.ORDER)
                self.__tx_hash_to_order_info[result.tx_hash] = OrderInfo(gas_price_wei, order.base_ccy_qty,
                                                                         order.quote_ccy_qty)
                self._request_cache.add_or_update_request_in_redis(client_request_id)

                return 200, {'result': {'tx_hash': result.tx_hash, 'nonce': result.nonce}}
            else:
                self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
                return 400, {'error': {'code': result.error_type.value, 'message': result.error_message}}

        except Exception as e:
            self._logger.exception(f'Failed to insert order: %r', e)
            if len(e.args) and ('message' in e.args[0] and 'nonce too low' in e.args[0]['message']):
                # Means a cancel/amend for this txn reached arbitrum sequencer first
                # Not finalising order here as finalisation will happen in subsequent cancel/amend block
                return 200, {'error': {'message': repr(e)}}
            else:
                self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
                self.__orders_pre_finalisation_clean_up(order)
                return 400, {'error': {'message': repr(e)}}

    async def _cancel_all(self, path, params, received_at_ms):
        try:
            assert params['request_type'] in ['ORDER', 'TRANSFER', 'APPROVE'], 'Unknown transaction type'
            request_type = RequestType[params['request_type']]

            self._logger.debug(f'Canceling all requests, request_type={request_type.name}')

            cancel_requested = []
            failed_cancels = []
            # TODO- Latency Improvement - use asyncio.gather()
            for request in self._request_cache.get_all(request_type):
                try:
                    if request.request_status != RequestStatus.PENDING or request.nonce is None:
                        continue
                    gas_price_wei = self._get_gas_price(request, priority_fee=PriorityFee.Fast)
                    if request.request_status == RequestStatus.CANCEL_REQUESTED and \
                            request.used_gas_prices_wei[-1] >= gas_price_wei:
                        self._logger.info(
                            f'Not sending cancel request for client_request_id={request.client_request_id} '
                            f'as cancel with greater than or equal to the gas_price_wei={gas_price_wei} already in progress')
                        cancel_requested.append(request.client_request_id)
                        continue

                    if len(request.used_gas_prices_wei) > 0:
                        gas_price_wei = max(gas_price_wei, int(1.1 * request.used_gas_prices_wei[-1]))

                    ok, reason = self._check_max_allowed_gas_price(gas_price_wei)
                    if not ok:
                        self._logger.error(
                            f'Not sending cancel request for client_request_id={request.client_request_id}: {reason}')
                        failed_cancels.append(request.client_request_id)
                        continue

                    self._logger.debug(f'Canceling={request}, gas_price_wei={gas_price_wei}')
                    result = await self._cancel_transaction(request, gas_price_wei)
                    if result.error_type == ErrorType.NO_ERROR:
                        request.tx_hashes.append((result.tx_hash, RequestType.CANCEL.name))
                        request.used_gas_prices_wei.append(gas_price_wei)
                        request.request_status = RequestStatus.CANCEL_REQUESTED
                        self._transactions_status_poller.add_for_polling(result.tx_hash, request.client_request_id,
                                                                         RequestType.CANCEL)
                        self._request_cache.add_or_update_request_in_redis(request.client_request_id)
                        cancel_requested.append(request.client_request_id)
                    else:
                        failed_cancels.append(request.client_request_id)

                except Exception as ex:
                    self._logger.exception(f'Failed to cancel request={request.client_request_id}: %r', ex)
                    failed_cancels.append(request.client_request_id)

            return 400 if failed_cancels else 200, {'cancel_requested': cancel_requested,
                                                    'failed_cancels': failed_cancels}
        except Exception as e:
            self._logger.exception(f'Failed to cancel all: %r', e)
            return 400, {'error': {'message': str(e)}}

    async def _get_all_open_requests(self, path, params, received_at_ms):
        return await super()._get_all_open_requests(path, params, received_at_ms)

    async def on_new_connection(self, ws):
        return

    async def process_request(self, ws, request_id, method, params: dict):
        return False

    async def _approve(self, request, gas_price_wei, nonce=None):
        return await self._api.approve(request.symbol, request.amount, request.gas_limit, gas_price_wei, nonce)

    async def _transfer(self, request, gas_price_wei, nonce=None):
        path = request.request_path
        symbol = request.symbol
        address_to = request.address_to
        amount = request.amount
        gas_limit = request.gas_limit
        if path == '/private/withdraw':
            assert address_to is not None
            return await self._api.withdraw(symbol, address_to, amount, gas_limit, gas_price_wei)
        else:
            assert False

    async def _amend_transaction(self, request, params, gas_price_wei):
        result: Optional[ApiResult] = None
        if request.request_type == RequestType.ORDER:
            if request.nonce is None:
                self._logger.debug(f"Amend requested before setting nonce "
                                   f"for Client Request Id".format(request.client_request_id))

                return ApiResult(error_type=ErrorType.TRANSACTION_FAILED,
                                 error_message=f"RETRY. Insert pending for request: {request}")

            instrument = self.__instruments.get_instrument(InstrumentId(self.__exchange_name, request.symbol))
            base_ccy_symbol = instrument.base_currency
            quote_ccy_symbol = instrument.quote_currency

            timeout_s = int(time.time() + params['timeout_s'])
            request.deadline_since_epoch_s = timeout_s
            request.base_ccy_qty = Decimal(params["base_ccy_qty"])
            request.quote_ccy_qty = Decimal(params["quote_ccy_qty"])

            if not self.__validate_tokens_address(instrument.native_code, base_ccy_symbol, quote_ccy_symbol):
                ApiResult(error_type=ErrorType.TRANSACTION_FAILED, error_message='unexpected instrument native code')

            if request.side == Side.BUY:
                result = await self._api.swap_exact_output_single(
                    quote_ccy_symbol, base_ccy_symbol, request.quote_ccy_qty, request.base_ccy_qty, request.fee_rate,
                    timeout_s, request.gas_limit, gas_price_wei, nonce=request.nonce)
            else:
                result = await self._api.swap_exact_input_single(
                    base_ccy_symbol, quote_ccy_symbol, request.base_ccy_qty, request.quote_ccy_qty, request.fee_rate,
                    timeout_s, request.gas_limit, gas_price_wei, nonce=request.nonce)

            self.__tx_hash_to_order_info[result.tx_hash] = OrderInfo(gas_price_wei, request.base_ccy_qty,
                                                                     request.quote_ccy_qty)
        elif request.request_type == RequestType.TRANSFER:
            result = await self._api.withdraw(request.symbol, request.address_to, request.amount,
                                              request.gas_limit, gas_price_wei, nonce=request.nonce)
        elif request.request_type == RequestType.APPROVE:
            result = await self._api.approve(request.symbol, request.amount, request.gas_limit,
                                             gas_price_wei, nonce=request.nonce)
        else:
            raise Exception('Unsupported request type for amending')

        if result is not None:
            if result.error_type == ErrorType.NO_ERROR:
                self._api.update_next_nonce_to_use(request.nonce+1)
        return result

    async def _cancel_transaction(self, request, gas_price_wei):
        if request.request_type in [RequestType.ORDER, RequestType.TRANSFER, RequestType.APPROVE]:
            try:
                if request.nonce is None:
                    # TODO - Improvement to do early cancellations can be done here
                    self._logger.debug(f"Cancellation requested before setting nonce "
                                       f"for Client Request Id".format(request.client_request_id))
                    return ApiResult(error_type=ErrorType.TRANSACTION_FAILED,
                                     error_message=f"RETRY. Insert pending for {request}")

                result = await self._api.cancel_transaction(request.nonce, gas_price_wei)
                if result.error_type == ErrorType.NO_ERROR:
                    self._api.update_next_nonce_to_use(request.nonce+1)
                return result
            except Exception as e:
                if len(e.args) and ("message" in e.args[0] and "nonce too low" in e.args[0]["message"]):
                    return ApiResult(error_type=ErrorType.TRANSACTION_FAILED,
                                     error_message=f"{request} already mined!")
                raise e

        else:
            raise Exception(f"Cancelling not supported for the {request.request_type}")

    async def get_transaction_receipt(self, request, tx_hash):
        return await self._api.get_transaction_receipt(tx_hash)

    def _get_gas_price(self, request, priority_fee: PriorityFee):
        return self.__base_block_gas_price

    def __populate_orders_dex_specifics(self, order_request: OrderRequest, mined_tx_hash: str):
        order_info = None
        if mined_tx_hash:
            order_info = self.__tx_hash_to_order_info.get(mined_tx_hash)
        if order_info:
            order_request.dex_specific["mined_tx_gas_price_wei"] = order_info.gas_price_wei
            order_request.dex_specific["mined_tx_base_ccy_qty"] = str(order_info.base_ccy_qty)
            order_request.dex_specific["mined_tx_quote_ccy_qty"] = str(order_info.quote_ccy_qty)
        else:
            self._logger.error(f"Did not find order_info for {mined_tx_hash}")

    async def on_request_status_update(self, client_request_id, request_status, tx_receipt: dict,
                                       mined_tx_hash: str = None):
        request = self.get_request(client_request_id)
        if request is None:
            return

        if request_status == RequestStatus.SUCCEEDED and request.request_type == RequestType.ORDER:
            self.__populate_orders_dex_specifics(request, mined_tx_hash)
            await self.__compute_exec_price(request, tx_receipt)

        if request.request_type == RequestType.ORDER:
            self.__orders_pre_finalisation_clean_up(request)
        await super().on_request_status_update(client_request_id, request_status, tx_receipt, mined_tx_hash)

        if request.request_type == RequestType.ORDER:
            event = {
                'jsonrpc': '2.0',
                'method': 'subscription',
                'params': {
                    'channel': 'ORDER',
                    'data': request.to_dict()
                }
            }

            await self._event_sink.on_event('ORDER', event)
        else:
            self._logger.debug(f"On request status update: {request}")

    async def __get_tx_status_ws(self):
        self.pantheon.spawn(self.__receive_ws_messages())

        while True:
            try:
                self._logger.info(
                    "[WS] Subscribing to get WS update for all mined transaction for the wallet")
                await self._api.subscribe_alchemy_mined_transactions(self.msg_queue)
                await self._api.get_public_websocket_status().wait_until_disconnected()
                await self._api.get_public_websocket_status().wait_until_connected()
            except Exception as e:
                self._logger.exception(
                    f'Error occurred in alchemy_mined_transactions ws subscription: %r', e)
                await self.pantheon.sleep(2)

    async def __receive_ws_messages(self):
        while True:
            try:
                message = await self.msg_queue.get()
                self._logger.info("[WS] [MESSAGE] %s", message)

                tx_hash = message['params']['result']['transaction']['hash']
                await self._transactions_status_poller.poll_for_status(tx_hash)
            except Exception as e:
                self._logger.exception(
                    f'Error occurred while handling WS message: %r', e)

    async def __compute_exec_price(self, request: OrderRequest, tx_receipt: dict):
        try:
            for log in tx_receipt['logs']:
                topic = Web3.to_hex(log['topics'][0])

                # 0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67 is the topic for the Swap event
                if topic == '0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67':
                    swap_log = self._api.get_swap_log(log['address'], tx_receipt)
                    self._logger.debug(f'Swap_log={swap_log}')
                    base_ccy_symbol, quote_ccy_symbol, instrument = self.__split_symbol_to_base_quote_ccy(
                        request.symbol)
                    token0_amount = int(swap_log[0]['args']['amount0'])
                    token1_amount = int(swap_log[0]['args']['amount1'])

                    if request.side == Side.BUY:
                        if token0_amount > 0:
                            base_ccy_amount = Decimal(
                                self._api.from_native_amount(base_ccy_symbol, abs(token1_amount)))
                            quote_ccy_amount = Decimal(
                                self._api.from_native_amount(quote_ccy_symbol, token0_amount))
                        else:
                            base_ccy_amount = Decimal(
                                self._api.from_native_amount(base_ccy_symbol, abs(token0_amount)))
                            quote_ccy_amount = Decimal(
                                self._api.from_native_amount(quote_ccy_symbol, token1_amount))
                    else:
                        if token0_amount > 0:
                            base_ccy_amount = Decimal(
                                self._api.from_native_amount(base_ccy_symbol, token0_amount))
                            quote_ccy_amount = Decimal(
                                self._api.from_native_amount(quote_ccy_symbol, abs(token1_amount)))
                        else:
                            base_ccy_amount = Decimal(
                                self._api.from_native_amount(base_ccy_symbol, token1_amount))
                            quote_ccy_amount = Decimal(
                                self._api.from_native_amount(quote_ccy_symbol, abs(token0_amount)))

                    request.exec_price = round(
                        quote_ccy_amount / base_ccy_amount, 8).normalize()
        except Exception as ex:
            self._logger.exception(f'Error occurred while computing execution price of request={request}: %r', ex)

    async def start(self, private_key):

        self.__instruments = await self.pantheon.get_instruments_live_source(
            exchanges=[self.__exchange_name],
            symbols=[],
            kinds=[],
            usage=InstrumentUsageExchanges.TradableOnly,
            lifecycles=[InstrumentLifecycle.ACTIVE],
            rmq_conn_name='url')

        file_prefix = os.path.dirname(os.path.realpath(__file__))
        addresses_whitelists_file_path = file_prefix + self.__contract_addresses_file_path
        self._logger.debug(f'Loading addresses whitelists from {addresses_whitelists_file_path}')
        with open(addresses_whitelists_file_path, 'r') as contracts_address_file:
            contracts_address_json = json.load(contracts_address_file)[self.__chain_name]

            tokens_list_json = contracts_address_json["tokens"]
            self.__tokens_from_res_file = {}
            for token_json in tokens_list_json:
                symbol = token_json["symbol"]
                if symbol in self._withdrawal_address_whitelists_from_res_file:
                    raise RuntimeError(f'Duplicate token : {symbol} in contracts_address file')
                for withdrawal_address in token_json["valid_withdrawal_addresses"]:
                    self._withdrawal_address_whitelists_from_res_file[symbol].add(
                        Web3.to_checksum_address(withdrawal_address))

                if symbol != self.__native_token:
                    self.__tokens_from_res_file[symbol] = ERC20Token(token_json["symbol"],
                                                                     Web3.to_checksum_address(token_json["address"]))

            uniswap_router_address = Web3.to_checksum_address(contracts_address_json["uniswap_router_address"])

        await self._api.initialize(private_key, uniswap_router_address, self.__tokens_from_res_file.values())

        await super().start(private_key)

        max_nonce_loaded = self._request_cache.get_max_nonce()
        self._api.initialize_starting_nonce(max_nonce_loaded + 1)

        self.pantheon.spawn(self.__get_tx_status_ws())

        self.started = True

    def _on_fireblocks_tokens_whitelist_refresh(self, tokens_from_fireblocks: dict):
        for symbol, (_, address) in tokens_from_fireblocks.items():
            if symbol == 'ETHAETH':
                symbol = self.__native_token

            if len(address) == 0:
                assert symbol == self.__native_token
                continue

            address = Web3.to_checksum_address(address)
            if symbol in self.__tokens_from_res_file:
                if address != self.__tokens_from_res_file[symbol].address:
                    self._logger.error(
                        f'Symbol={symbol} address did not match: Fireblocks: {address} Resources File: {self.__tokens_from_res_file[symbol].address}')
                continue

            try:
                self._api._add_or_update_erc20_contract(symbol, address)
            except Exception as ex:
                self._logger.exception(
                    f'Error in adding or updating ERC20 token (symbol={symbol}, address={address}): %r', ex)

    def __validate_tokens_address(self, instr_native_code: str, base_ccy: str, quote_ccy: str) -> bool:
        base_ccy_address = self._api.get_erc20_contract(base_ccy).address
        quote_ccy_address = self._api.get_erc20_contract(quote_ccy).address
        return instr_native_code.upper().endswith("-" + base_ccy_address.upper() + "-" + quote_ccy_address.upper())

    def __orders_pre_finalisation_clean_up(self, order_request: OrderRequest):
        for tx_hash, _ in order_request.tx_hashes:
            self.__tx_hash_to_order_info.pop(tx_hash, None)
