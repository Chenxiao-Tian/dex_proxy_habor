import asyncio
import boto3
import base64
import json
import os
import time
import uuid

from decimal import Decimal
from hexbytes import HexBytes

from pantheon import Pantheon
from pantheon.instruments_source import InstrumentLifecycle, InstrumentsLiveSource, InstrumentUsageExchanges
from pantheon.market_data_types import InstrumentId, Side

from pyutils.exchange_apis.uniswapV3_api import *
from pyutils.exchange_connectors import ConnectorType

from ..dex_common import DexCommon


class UniswapV3Bloxroute(DexCommon):
    CHANNELS = ['ORDER']

    def __init__(self, pantheon: Pantheon, config, server, event_sink):
        super().__init__(pantheon, ConnectorType.UniswapV3, config, server, event_sink)

        self.msg_queue = asyncio.Queue()

        self._server.register(
            'POST', '/private/insert-order', self.__insert_order)

        # TODO: maybe move this endpoint to dex_common
        self._server.register(
            'POST', '/private/wrap-unwrap-eth', self.__wrap_unwrap_eth)

        self.__instruments: InstrumentsLiveSource = None
        self.__exchange_name = config['exchange_name']
        self.__chain_name = config['chain_name']
        self.__native_token = config['native_token']

        self.__targeted_block = 0
        self.__targeted_block_uuid: str = None
        self.__bundles_sent_for_targeted_block = 0

        self.__max_bundles_per_block = self._config['max_bundles_per_block']

        self.__raw_txs_in_targeted_block = []
        self.__order_client_requ_id_vs_raw_txs = {}

    async def __insert_order(self, path, params: dict, received_at_ms):
        client_request_id = ''
        try:
            client_request_id = params['client_request_id']

            if self._request_cache.get(client_request_id) is not None:
                return 400, {'error': {'message': f'client_request_id={client_request_id} is already known'}}

            symbol = params['symbol']
            base_ccy_qty = Decimal(params['base_ccy_qty'])
            quote_ccy_qty = Decimal(params['quote_ccy_qty'])
            assert params['side'] == 'BUY' or params['side'] == 'SELL', 'Unknown order side'
            side = Side.BUY if params['side'] == 'BUY' else Side.SELL
            fee_rate = int(params['fee_rate'])
            gas_price_wei = int(params['gas_price_wei'])
            gas_limit = 500000  # TODO: Check for the most suitable value
            timeout_s = int(time.time() + params['timeout_s'])

            instrument = self.__instruments.get_instrument(
                InstrumentId(self.__exchange_name, symbol))
            base_ccy_symbol = instrument.base_currency
            quote_ccy_symbol = instrument.quote_currency

            order = OrderRequest(client_request_id, symbol, base_ccy_qty,
                                 quote_ccy_qty, side, fee_rate, gas_limit, timeout_s, received_at_ms)

            self._logger.debug(
                f'Inserting={order}, gas_price_wei={gas_price_wei}')
            self._request_cache.add(order)

            if (not self.__validate_tokens_address(instrument.native_code, base_ccy_symbol, quote_ccy_symbol)):
                self._request_cache.finalise_request(
                    client_request_id, RequestStatus.FAILED)
                return 400, {'error': {'message': 'unexpected instrument native code'}}

            next_block_num, next_block_uuid = await self.__update_and_get_next_block_num()

            targeted_block = params.get('targeted_block')
            if ((targeted_block is not None) and (int(targeted_block) != next_block_num)):
                self._request_cache.finalise_request(
                    client_request_id, RequestStatus.FAILED)
                return 400, {'error': {'message': f'targeted_block={targeted_block} != next_block={next_block_num}'}}

            ok, reason = self.__validate_can_send_via_blx(gas_price_wei)
            if not ok:
                self._request_cache.finalise_request(
                    client_request_id, RequestStatus.FAILED)
                return 400, {'error': {'message': reason}}

            self.__bundles_sent_for_targeted_block += 1

            nonce = await self._api.get_total_txs_so_far() + len(self.__raw_txs_in_targeted_block)

            if side == Side.BUY:
                built_tx = self._api.build_swap_exact_output_single_tx(
                    quote_ccy_symbol, base_ccy_symbol, quote_ccy_qty, base_ccy_qty, fee_rate, timeout_s,
                    gas_limit, gas_price_wei, nonce)
            else:
                built_tx = self._api.build_swap_exact_input_single_tx(
                    base_ccy_symbol, quote_ccy_symbol, base_ccy_qty, quote_ccy_qty, fee_rate, timeout_s,
                    gas_limit, gas_price_wei, nonce)

            signed_tx = self._api.sign_tx(built_tx)
            raw_tx = signed_tx.rawTransaction.hex()[2:]
            self.__raw_txs_in_targeted_block.append(raw_tx)
            self.__order_client_requ_id_vs_raw_txs[client_request_id] = raw_tx

            tx_hash = Web3.to_hex(signed_tx.hash)
            order.order_id = tx_hash
            order.nonce = nonce
            order.tx_hashes.append((tx_hash, RequestType.ORDER.name))
            order.used_gas_prices_wei.append(gas_price_wei)
            order.dex_specific = {'targeted_block_num': next_block_num, 'uuid': next_block_uuid}

            self._transactions_status_poller.add_for_polling(tx_hash, client_request_id, RequestType.ORDER)

            await self._api.send_bundle(self.__raw_txs_in_targeted_block, next_block_num, next_block_uuid)

            self._request_cache.add_or_update_request_in_redis(client_request_id)

            return 200, {'result': {'order_id': tx_hash, 'nonce': nonce}}

        except Exception as e:
            self._logger.exception(f'Failed to insert order: %r', e)
            self._request_cache.finalise_request(client_request_id, RequestStatus.FAILED)
            return 400, {'error': {'message': repr(e)}}

    async def __wrap_unwrap_eth(self, path, params: dict, received_at_ms):
        client_request_id = ''
        try:
            client_request_id = params['client_request_id']

            if self._request_cache.get(client_request_id) is not None:
                return 400, {'error': {'message': f'client_request_id={client_request_id} is already known'}}

            request = params['request']
            assert request == 'wrap' or request == 'unwrap', 'Unknown request, should be either wrap or unwrap'
            amount = Decimal(params['amount'])
            gas_price_wei = int(params['gas_price_wei'])
            gas_limit = int(params['gas_limit'])

            wrap_unwrap = WrapUnwrapRequest(client_request_id, request, amount, gas_limit, received_at_ms)

            self._logger.debug(
                f'{"Wrapping" if wrap_unwrap.request == "wrap" else "Unwrapping"}={wrap_unwrap}, gas_price_wei={gas_price_wei}')
            self._request_cache.add(wrap_unwrap)

            next_block_num, next_block_uuid = await self.__update_and_get_next_block_num()

            ok, reason = self.__validate_can_send_via_blx(gas_price_wei)
            if not ok:
                self._request_cache.finalise_request(
                    client_request_id, RequestStatus.FAILED)
                return 400, {'error': {'message': reason}}

            self.__bundles_sent_for_targeted_block += 1

            nonce = await self._api.get_total_txs_so_far() + len(self.__raw_txs_in_targeted_block)

            if wrap_unwrap.request == 'wrap':
                built_tx = self._api.build_wrap_tx('WETH', amount, gas_limit, gas_price_wei, nonce)
            else:
                built_tx = self._api.build_unwrap_tx('WETH', amount, gas_limit, gas_price_wei, nonce)
            signed_tx = self._api.sign_tx(built_tx)

            self.__raw_txs_in_targeted_block.append(signed_tx.rawTransaction.hex()[2:])
            tx_hash = Web3.to_hex(signed_tx.hash)
            wrap_unwrap.nonce = nonce
            wrap_unwrap.tx_hashes.append((tx_hash, RequestType.WRAP_UNWRAP.name))
            wrap_unwrap.used_gas_prices_wei.append(gas_price_wei)
            wrap_unwrap.dex_specific = {'targeted_block_num': next_block_num, 'uuid': next_block_uuid}

            self._transactions_status_poller.add_for_polling(tx_hash, client_request_id, RequestType.WRAP_UNWRAP)

            await self._api.send_bundle(self.__raw_txs_in_targeted_block, next_block_num, next_block_uuid)

            self._request_cache.add_or_update_request_in_redis(client_request_id)

            return 200, {'tx_hash': tx_hash}

        except Exception as e:
            self._logger.exception(f'Failed to handle wrap_unwrap request: %r', e)
            self._request_cache.finalise_request(
                client_request_id, RequestStatus.FAILED)
            return 400, {'error': {'message': repr(e)}}

    async def _cancel_all(self, path, params, received_at_ms):
        return 400, {'error': {'message': repr(Exception('Cancel all request not supported by uni3 dex-proxy with '
                                                         'Bloxroute integrated'))}}

    async def _get_all_open_requests(self, path, params, received_at_ms):
        return await super()._get_all_open_requests(path, params, received_at_ms)

    async def on_new_connection(self, ws):
        return

    async def process_request(self, ws, request_id, method, params: dict):
        return False

    async def _approve(self, request, symbol, amount, gas_limit, gas_price_wei, nonce=None):
        next_block_num, next_block_uuid = await self.__update_and_get_next_block_num()

        ok, reason = self.__validate_can_send_via_blx(gas_price_wei)
        if not ok:
            return ApiResult(error_type=ErrorType.TRANSACTION_FAILED, error_message=reason)

        self.__bundles_sent_for_targeted_block += 1

        nonce = await self._api.get_total_txs_so_far() + len(self.__raw_txs_in_targeted_block)

        built_tx = self._api.build_approve_tx(symbol, amount, gas_limit, gas_price_wei, nonce)
        signed_tx = self._api.sign_tx(built_tx)
        self.__raw_txs_in_targeted_block.append(signed_tx.rawTransaction.hex()[2:])
        tx_hash = Web3.to_hex(signed_tx.hash)
        request.dex_specific = {'targeted_block_num': next_block_num, 'uuid': next_block_uuid}

        await self._api.send_bundle(self.__raw_txs_in_targeted_block, next_block_num, next_block_uuid)

        return ApiResult(nonce, tx_hash)

    async def _transfer(self, request, path, symbol, address_to, amount, gas_limit, gas_price_wei, nonce=None):
        if path == '/private/withdraw':
            assert address_to is not None

            next_block_num, next_block_uuid = await self.__update_and_get_next_block_num()

            ok, reason = self.__validate_can_send_via_blx(gas_price_wei)
            if not ok:
                return ApiResult(error_type=ErrorType.TRANSACTION_FAILED, error_message=reason)

            self.__bundles_sent_for_targeted_block += 1

            nonce = await self._api.get_total_txs_so_far() + len(self.__raw_txs_in_targeted_block)

            built_tx = self._api.build_withdraw_tx(
                symbol, address_to, amount, gas_limit, gas_price_wei, nonce)
            signed_tx = self._api.sign_tx(built_tx)
            self.__raw_txs_in_targeted_block.append(
                signed_tx.rawTransaction.hex()[2:])
            tx_hash = Web3.to_hex(signed_tx.hash)
            request.dex_specific = {'targeted_block_num': next_block_num, 'uuid': next_block_uuid}

            await self._api.send_bundle(self.__raw_txs_in_targeted_block, next_block_num, next_block_uuid)

            return ApiResult(nonce, tx_hash)
        else:
            assert False

    async def _amend_transaction(self, request: Request, params, gas_price_wei):
        if request.request_type != RequestType.ORDER:
            return ApiResult(error_type=ErrorType.TRANSACTION_FAILED,
                      error_message=
                      'Amend request not supported for non-order request by uni3 dex-proxy with Bloxroute integrated')

        next_block_num, next_block_uuid = await self.__update_and_get_next_block_num()

        ok, reason = self.__validate_can_send_via_blx(gas_price_wei)
        if not ok:
            return ApiResult(error_type=ErrorType.TRANSACTION_FAILED, error_message=reason)

        if request.client_request_id not in self.__order_client_requ_id_vs_raw_txs:

            if request.nonce is None:
                # Can happen if amend is too soon after insert
                # Insert processing might be stuck at some `await` and the amend is processed before the insert
                return ApiResult(error_type=ErrorType.TRANSACTION_FAILED, error_message='RETRY. Cannot Amend: not inserted yet.')
            else:
                return ApiResult(error_type=ErrorType.TRANSACTION_FAILED, error_message='Cannot Amend: missed targeted block')

        old_raw_tx = self.__order_client_requ_id_vs_raw_txs[request.client_request_id]

        raw_tx_idx = 0
        while raw_tx_idx < len(self.__raw_txs_in_targeted_block):
            if self.__raw_txs_in_targeted_block[raw_tx_idx] == old_raw_tx:
                break
            raw_tx_idx += 1

        if raw_tx_idx >= len(self.__raw_txs_in_targeted_block):
            # Should not happen ever. If somehow happens then investigate and fix.
            raise Exception('Internal Error: Failed to Amend. Reach out to Dev.')

        self.__bundles_sent_for_targeted_block += 1

        instrument = self.__instruments.get_instrument(
            InstrumentId(self.__exchange_name, request.symbol))
        base_ccy_symbol = instrument.base_currency
        quote_ccy_symbol = instrument.quote_currency

        timeout_s = int(time.time() + params['timeout_s'])
        request.deadline_since_epoch_s = timeout_s

        if (not self.__validate_tokens_address(instrument.native_code, base_ccy_symbol, quote_ccy_symbol)):
            return ApiResult(error_type=ErrorType.TRANSACTION_FAILED, error_message='unexpected instrument native code')

        if request.side == Side.BUY:
            built_tx = self._api.build_swap_exact_output_single_tx(
                quote_ccy_symbol, base_ccy_symbol, request.quote_ccy_qty, request.base_ccy_qty, request.fee_rate,
                timeout_s, request.gas_limit, gas_price_wei, nonce=request.nonce)
        else:
            built_tx = self._api.build_swap_exact_input_single_tx(
                base_ccy_symbol, quote_ccy_symbol, request.base_ccy_qty, request.quote_ccy_qty, request.fee_rate,
                timeout_s, request.gas_limit, gas_price_wei, nonce=request.nonce)

        signed_tx = self._api.sign_tx(built_tx)
        new_raw_tx = signed_tx.rawTransaction.hex()[2:]
        self.__raw_txs_in_targeted_block[raw_tx_idx] = new_raw_tx
        self.__order_client_requ_id_vs_raw_txs[request.client_request_id] = new_raw_tx

        tx_hash = Web3.to_hex(signed_tx.hash)

        await self._api.send_bundle(self.__raw_txs_in_targeted_block, next_block_num, next_block_uuid)

        return ApiResult(nonce=request.nonce, tx_hash=tx_hash)

    async def _cancel_transaction(self, request, gas_price_wei):
        raise Exception(
            'Cancel request not supported by uni3 dex-proxy with Bloxroute integrated')

    async def get_transaction_receipt(self, request, tx_hash):
        return await self._api.get_transaction_receipt(tx_hash)

    def _get_gas_price(self, request, priority_fee):
        raise Exception(
            'Gas Price Tracker not supported by uni3 dex-proxy with Bloxroute integrated')

    async def on_request_status_update(self, client_request_id, request_status, tx_receipt: dict):
        request = self.get_request(client_request_id)
        if (request == None):
            return

        if (request_status == RequestStatus.SUCCEEDED and request.request_type == RequestType.ORDER):
            await self.__compute_exec_price(request, tx_receipt)

        await super().on_request_status_update(client_request_id, request_status, tx_receipt)

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
            self._logger.debug(f'On request status update: {request}')

    async def __get_tx_status_ws(self):
        self.pantheon.spawn(self.__get_mined_tx_hash())

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

    async def __get_mined_tx_hash(self):
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
                    swap_log = self._api.get_swap_log(
                        log['address'], tx_receipt)
                    self._logger.debug(f'Swap_log={swap_log}')
                    # https://docs.uniswap.org/contracts/v3/reference/core/interfaces/pool/IUniswapV3PoolEvents#swap

                    # Sample swap_log:
                    # (AttributeDict({'args': AttributeDict({'sender': '0xE592427A0AEce92De3Edee1F18E0157C05861564',
                    # 'recipient': '0x03CdE1E0bc6C1e096505253b310Cf454b0b462FB', 'amount0': 100000000000, 'amount1': -332504806775,
                    # 'sqrtPriceX96': 144687485274156549416468062839, 'liquidity': 580197578039432673188, 'tick': 12045}),
                    # 'event': 'Swap', 'logIndex': 222, 'transactionIndex': 120, 'transactionHash':
                    # HexBytes('0x858c864355ca60d342c2b250ed4d641d66f4a922039ce4d2307101d75d5450eb'),
                    # 'address': '0x03AfDFB6CaBd6BA2a9e54015226F67E9295a9Bea', 'blockHash':
                    # HexBytes('0xdd5186fa2d0298777165467ddfcc944b073f68a9d1060b332c3fdfa7b5e90fbc'), 'blockNumber': 9065089}),)

                    # positive amount means that the corresponding token is added to the pool while negative amount means corresponding token is taken out of the pool

                    instrument = self.__instruments.get_instrument(
                        InstrumentId(self.__exchange_name, request.symbol))
                    base_ccy_symbol = instrument.base_currency
                    quote_ccy_symbol = instrument.quote_currency

                    token0_amount = Decimal(swap_log[0]['args']['amount0'])
                    token1_amount = Decimal(swap_log[0]['args']['amount1'])

                    if (request.side == Side.BUY):
                        if (token0_amount > 0):
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
                        if (token0_amount > 0):
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
                        quote_ccy_amount/base_ccy_amount, 8).normalize()
        except Exception as ex:
            self._logger.exception(
                f'Error occurred while computing execution price of request={request}: %r', ex)

    # finalises requests who missed to get minned in the targeted block
    async def __finalise_missed_requests(self):
        while True:
            try:
                await self.pantheon.sleep(1)

                self._logger.debug('Polling for finalising requests missing targeted block')

                open_requests = self._request_cache.get_all()
                if len(open_requests) == 0:
                    continue

                curr_block_num = await self._api.get_current_block_num()

                # Caching: so that we don't call rpc method self._api.get_block for same block_num
                block_num_vs_block_data = {}

                for request in open_requests:
                    try:
                        if (
                            request.request_status == RequestStatus.SUCCEEDED
                            or request.request_status == RequestStatus.CANCELED
                            or request.request_status == RequestStatus.FAILED
                        ):
                            continue

                        targeted_block_num = request.dex_specific.get('targeted_block_num')
                        if  targeted_block_num == None or targeted_block_num > curr_block_num:
                            continue

                        if (targeted_block_num not in block_num_vs_block_data) or \
                            (block_num_vs_block_data[targeted_block_num] == None):
                            targeted_block_data = await self._api.get_block(targeted_block_num)
                            block_num_vs_block_data[targeted_block_num] = targeted_block_data

                            self._logger.debug(f'block_num={targeted_block_num}, block_data={targeted_block_data}')
                        else:
                            targeted_block_data = block_num_vs_block_data[targeted_block_num]

                        if targeted_block_data == None:
                            continue

                        request_mined = False
                        for tx_hash, _ in request.tx_hashes:
                            if HexBytes(tx_hash) in targeted_block_data.transactions:
                                self._logger.debug(f'tx_hash={tx_hash} found in the targeted_block_num={targeted_block_num}')
                                request_mined = True
                                break

                        if (not request_mined):
                            await self.on_request_status_update(request.client_request_id, RequestStatus.FAILED, None)
                        # else:
                        #     transaction_status_poller will handle finalising the request

                    except Exception as ex:
                        # retry after 1 sec
                        self._logger.exception(
                            f'Error in polling tx_hashes of request={request} for finalising requests \
                                missing targeted block: %r', ex)
            except Exception as e:
                self._logger.exception(f'Error in polling for finalising request missing targeted block: %r', e)

    def __get_blx_authorisation_header(self) -> str:
        if 'blx_authorisation_header' in self._config:
            return self._config['blx_authorisation_header']
        else:
            session = boto3.Session()
            client = session.client(service_name='secretsmanager', region_name='ap-southeast-1')
            try:
                secret = client.get_secret_value(
                    SecretId=f'{self.pantheon.process_name}/3a5f7520d84c7b01d2a94f860d4202ba720')
                if 'SecretString' in secret:
                    auth_json = json.loads(secret['SecretString'])
                else:
                    decoded_binary_secret = base64.b64decode(secret['SecretBinary'])
                    auth_json = json.loads(decoded_binary_secret)
                return auth_json['auth_header']
            except Exception as ex:
                self._logger.exception(
                    f'Error in getting blx authorisation header: %r', ex)
                raise ex

    async def start(self, private_key):
        self.__instruments = await self.pantheon.get_instruments_live_source(
            exchanges=[self.__exchange_name],
            symbols=[],
            kinds=[],
            usage=InstrumentUsageExchanges.TradableOnly,
            lifecycles=[InstrumentLifecycle.ACTIVE],
            rmq_conn_name='url')

        file_prefix = os.path.dirname(os.path.realpath(__file__))
        addresses_whitelists_file_path = f'{file_prefix}/../../resources/uni3_contracts_address.json'
        self._logger.debug(
            f'Loading addresses whitelists from {addresses_whitelists_file_path}')
        with open(addresses_whitelists_file_path, 'r') as contracts_address_file:
            contracts_address_json = json.load(contracts_address_file)[
                self.__chain_name]

            tokens_list_json = contracts_address_json["tokens"]
            self.__tokens_from_res_file = {}
            for token_json in tokens_list_json:
                symbol = token_json["symbol"]
                if symbol in self._withdrawal_address_whitelists_from_res_file:
                    raise RuntimeError(
                        f'Duplicate token : {symbol} in contracts_address file')
                for withdrawal_address in token_json["valid_withdrawal_addresses"]:
                    self._withdrawal_address_whitelists_from_res_file[symbol].add(Web3.to_checksum_address(withdrawal_address))

                if symbol != self.__native_token:
                    self.__tokens_from_res_file[symbol] = ERC20Token(token_json["symbol"],
                                                                     Web3.to_checksum_address(token_json["address"]))

            uniswap_router_address = contracts_address_json["uniswap_router_address"]

        await self._api.initialize(private_key, uniswap_router_address, self.__tokens_from_res_file.values())

        await super().start(private_key)

        self.pantheon.spawn(self.__get_tx_status_ws())

        blx_authorisation_header = self.__get_blx_authorisation_header()
        await self._api.initialise_and_maintain_blx_mev_ws(blx_authorisation_header)

        self.pantheon.spawn(self.__finalise_missed_requests())

        self.started = True

    def _on_fireblocks_tokens_whitelist_refresh(self, tokens_from_fireblocks: dict):
        if self.started == False:
            return

        for symbol, (_, address) in tokens_from_fireblocks.items():
            address = Web3.to_checksum_address(address)
            if symbol in self.__tokens_from_res_file:
                if address != self.__tokens_from_res_file[symbol].address:
                    self._logger.error(f'Symbol={symbol} address did not match: Fireblocks: {address} Resources File: {self.__tokens_from_res_file[symbol].address}')
                continue

            try:
                self._api._add_or_update_erc20_contract(symbol, Web3.to_checksum_address(address))
            except Exception as ex:
                self._logger.exception(f'Error in adding or updating ERC20 token (symbol={symbol}, address={address}): %r', ex)

    async def __update_and_get_next_block_num(self)-> tuple[int, str]:
        next_block_num = (await self._api.get_current_block_num()) + 1

        if (next_block_num > self.__targeted_block):
            self.__targeted_block = next_block_num
            self.__targeted_block_uuid = str(uuid.uuid4())
            self.__bundles_sent_for_targeted_block = 0
            self.__raw_txs_in_targeted_block = []
            self.__order_client_requ_id_vs_raw_txs = {}
        elif (next_block_num < self.__targeted_block):
            # Rare case but might happen when the node which served the call `self._api.get_current_block_num()` is lagging
            next_block_num = self.__targeted_block

        return next_block_num, self.__targeted_block_uuid

    def __validate_can_send_via_blx(self, gas_price_wei: int) -> tuple[bool, str]:
        if not self._api.is_blx_mev_ws_ready():
            # 'RETRY.' at the begining of the error msg will be used by the ES to know whether to retry amends
            return False, 'RETRY. Bloxroute mev WS not ready'

        if self.__bundles_sent_for_targeted_block >= self.__max_bundles_per_block:
            return False, 'Exhausted max bundles per block rate limit'

        return self._check_max_allowed_gas_price(gas_price_wei)

    def __validate_tokens_address(self, instr_native_code: str, base_ccy: str, quote_ccy: str) -> bool:
        base_ccy_address = self._api.get_erc20_contract(base_ccy).address
        quote_ccy_address = self._api.get_erc20_contract(quote_ccy).address
        return instr_native_code.upper().endswith("-" + base_ccy_address.upper() + "-" + quote_ccy_address.upper())