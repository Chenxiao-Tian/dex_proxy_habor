import logging
import signal
import functools
import weakref
from collections import defaultdict

from pantheon import Pantheon

from py_dex_common.web_server import WebServer

from py_dex_common.dexes.dex_common import DexCommon

from eth_account import Account

_logger = logging.getLogger('DexProxy')

class DexProxy:
    class Subscription:

        def __init__(self, ws):
            self.ws_ref = weakref.ref(ws)

        def __eq__(self, other):
            if not isinstance(other, DexProxy.Subscription):
                raise NotImplemented
            return self.ws_ref == other.ws_ref

        def __hash__(self):
            return hash(self.ws_ref)

    def __init__(self, pantheon: Pantheon, web_server: WebServer, exchange: DexCommon):
        self.pantheon = pantheon
        self.__subscriptions = defaultdict(set)
        self.__server = web_server
        self.__exchange = exchange

    def __get_private_key(self):
        if (
            "key_store_file_path" not in self.pantheon.config
            and "solana_secret_file_path" not in self.pantheon.config
        ):
            return None

        if "solana_secret_file_path" in self.pantheon.config:
            assert (
                "key_store_file_path" not in self.pantheon.config
            ), "can't have both eth and solana secret present"

            with open(
                self.pantheon.config["solana_secret_file_path"]
            ) as solana_secret_file:
                solana_secret = solana_secret_file.read()
                return [int(num) for num in solana_secret[1:-1].split(",")]

        key_store_file_path = self.pantheon.config["key_store_file_path"]

        def get_private_key_from_file(file_path):
            with open(file_path) as keyfile:
                encrypted_key = keyfile.read()
                private_key = Account.decrypt(encrypted_key, '')
                return private_key.hex()

        if isinstance(key_store_file_path, list):
            return [get_private_key_from_file(file_path) for file_path in key_store_file_path]

        return get_private_key_from_file(key_store_file_path)

    async def on_new_connection(self, ws):
        await self.__exchange.on_new_connection(ws)

    async def on_message(self, ws, msg: dict):
        try:
            request_id = msg['id']
            method = msg['method']
            params = msg['params']

            if method == 'subscribe':
                await self.__subscribe(ws, request_id, params)
            elif method == 'unsubscribe':
                await self.__unsubscribe(ws, request_id, params)
            else:
                if not await self.__exchange.process_request(ws, request_id, method, params):
                    _logger.critical(f'Unknown method {method} in {msg}')
                    await ws.close(message=f'Unknown method {method}')
        except Exception as e:
            _logger.exception(f'Failed to handle {msg}: %r', e)
            reply = {
                'jsonrpc': '2.0',
                'id': request_id,
                'error': {'message': str(e)}}
            await self.__server.send_json(ws, reply)

    async def __subscribe(self, ws, request_id: int, params: dict):
        reply = {'jsonrpc': '2.0', 'id': request_id}

        channel = params['channel']
        if channel not in self.__exchange.CHANNELS:
            reply['error'] = {'message': f'Channel {channel} does not exist'}
        else:
            sub = self.Subscription(ws)
            if sub not in self.__subscriptions[channel]:
                self.__subscriptions[channel].add(sub)
                _logger.debug(
                    f'Subscribed client(connection_id={id(ws)}) to {channel}')
            else:
                _logger.debug(
                    f'Client(connection_id={id(ws)}) already subscribed to {channel}')
            reply['result'] = [channel]

        await self.__server.send_json(ws, reply)

    async def __unsubscribe(self, ws, request_id: int, params: dict):
        reply = {'jsonrpc': '2.0', 'id': request_id}

        channel = params['channel']
        if channel not in self.__subscriptions:
            reply['error'] = {'message': f'Channel {channel} does not exist'}
        else:
            sub = self.Subscription(ws)
            if sub in self.__subscriptions[channel]:
                self.__subscriptions[channel].remove(sub)
                _logger.debug(
                    f'Unsubscribed client(connection_id={id(ws)}) from {channel}')
                reply['result'] = [channel]
            else:
                _logger.debug(
                    f'Client(connection_id={id(ws)}) not subscribed to {channel}')
                reply['result'] = []

        await self.__server.send_json(ws, reply)

    async def on_event(self, channel, event):
        _logger.debug(f'channel={channel}, event={event}')
        for sub in self.__subscriptions[channel]:
            ws = sub.ws_ref()
            if ws is not None:
                await self.__server.send_json(ws, event)

    def stop(self, sig):
        _logger.info(f'Receiving signal {sig}')
        self.__running = False

    async def run(self):
        self.pantheon.loop.add_signal_handler(
            signal.SIGTERM, functools.partial(
                self.stop, signal.SIGTERM))

        app_health = await self.pantheon.get_app_health(app_type='service')

        private_key = self.__get_private_key()
        await self.__exchange.start(private_key)

        await self.__server.start()

        self.__running = True
        app_health.running()

        while self.__running:
            for channel, subs in self.__subscriptions.items():
                self.__subscriptions[channel] = set(
                    filter(lambda sub: sub.ws_ref() is not None, subs))

            await self.pantheon.sleep(5)

        _logger.debug('Stopping')
        app_health.stopping()

        await self.__server.stop()

        app_health.stopped()

        await self.pantheon.sleep(1)
