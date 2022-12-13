import logging
import signal
import functools
import weakref
from typing import Dict, List
from collections import defaultdict
import os

from pantheon import Pantheon, StandardArgParser

from web_server import WebServer
from dexes import Dexalot

from eth_account import Account

import boto3
import ujson
import base64

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

        self.__server = WebServer(self.pantheon.config['server'], self.__on_message)

        dex_config = self.pantheon.config['dex']
        name = dex_config['name']
        if name == 'dexa':
            self.__exchange = Dexalot(pantheon, dex_config, self.__server, self)
        elif name == 'uniswap':
            raise NotImplementedError()
        else:
            raise Exception(f'Exchange {name} not supported')

    def __get_private_key(self):
        key_store_file = os.getenv('KEY_STORE_FILE')
        with open(key_store_file) as keyfile:
            encrypted_key = keyfile.read()
            private_key = Account.decrypt(encrypted_key, '')
            return private_key.hex()

    def __get_secrets(self):
        region_name = os.getenv('AWS_REGION')
        if region_name is None:
            region_name = 'ap-southeast-1'
        secret_id = os.getenv('SECRET_ID')
        if secret_id is None:
            _logger.warning('Environment variable SECRET_ID not found')
            return None

        secrets_client = boto3.client(service_name='secretsmanager', region_name=region_name)
        secret_value = secrets_client.get_secret_value(SecretId=secret_id)
        if 'SecretString' in secret_value:
            payload = ujson.loads(secret_value['SecretString'])
        else:
            decoded_binary_secret = base64.b64decode(secret_value['SecretBinary'])
            payload = ujson.loads(decoded_binary_secret)
        return payload

    async def __on_message(self, ws, msg: dict):
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
                _logger.debug(f'Subscribed client(connection_id={id(ws)}) to {channel}')
            else:
                _logger.debug(f'Client(connection_id={id(ws)}) already subscribed to {channel}')
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
                _logger.debug(f'Unsubscribed client(connection_id={id(ws)}) from {channel}')
                reply['result'] = [channel]
            else:
                _logger.debug(f'Client(connection_id={id(ws)}) not subscribed to {channel}')
                reply['result'] = []

        await self.__server.send_json(ws, reply)

    async def on_event(self, channel, event):
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
        secrets = self.__get_secrets()
        await self.__exchange.start(private_key, secrets)

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
