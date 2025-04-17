import logging
import signal
import functools
import weakref
from collections import defaultdict

from pantheon import Pantheon, StandardArgParser
from pyutils.exchange_connectors import ConnectorType

from web_server import WebServer
from dexes import Dexalot, UniswapV3, UniswapV3Bloxroute, Paradex, Lyra, Per, Hype, Native, Vert

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

    def __init__(self, pantheon: Pantheon):
        self.pantheon = pantheon

        # channel -> set of Subscription
        self.__subscriptions = defaultdict(set)

        self.__server = WebServer(self.pantheon.config['server'], self)

        dex_config = self.pantheon.config['dex']
        name = dex_config['name']
        if name == 'dexa':
            self.__exchange = Dexalot(
                pantheon, dex_config, self.__server, self)
        elif name == 'chainEth-uni3-blx':
            self.__exchange = UniswapV3Bloxroute(
                pantheon, dex_config, self.__server, self)
        elif name == 'chainArb-uni3':
            self.__exchange = UniswapV3(
                pantheon, dex_config, self.__server, self, ConnectorType.UniswapV3Arb)
        elif name in ['chainEth-uni3', 'chainGoerli-uni3']:
            self.__exchange = UniswapV3(
                pantheon, dex_config, self.__server, self, ConnectorType.UniswapV3)
        elif name == 'chainFlame-uni3':
            self.__exchange = UniswapV3(pantheon, dex_config, self.__server, self, ConnectorType.UniswapV3Astria)
        elif name == "chainBera-uni3":
            self.__exchange = UniswapV3(pantheon, dex_config, self.__server, self, ConnectorType.UniswapV3Bera)
        elif name == 'pdex':
            self.__exchange = Paradex(
                pantheon, dex_config, self.__server, self)
        elif name == 'lyra':
            self.__exchange = Lyra(
                pantheon, dex_config, self.__server, self)
        elif name == 'per':
            self.__exchange = Per(pantheon, dex_config, self.__server, self)
        elif name == 'hype':
            self.__exchange = Hype(pantheon, dex_config, self.__server, self)
        elif name == 'native':
            self.__exchange = Native(pantheon, dex_config, self.__server, self)
        elif name == 'vert':
            self.__exchange = Vert(pantheon, dex_config, self.__server, self)
        else:
            raise Exception(f'Exchange {name} not supported')

    def __get_private_key(self):
        key_store_file_path = self.pantheon.config['key_store_file_path']

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


if __name__ == '__main__':
    pt = Pantheon('dex_proxy')
    parser = StandardArgParser('Dex Proxy')
    pt.load_args_and_config(parser)
    proxy = DexProxy(pt)
    pt.run_app(proxy.run())
