import json
import logging
import time

from .transactions_status_poller import TransactionsStatusPoller
from datetime import timedelta
from pantheon import Pantheon
from pyutils.exchange_apis.uniswapV3_api import *
from collections import deque
from typing import Optional
from utils.redis_batch_executor import RedisBatchExecutor


class RequestsCache:
    def __init__(self, pantheon: Pantheon, api: UniswapV3Api, config):
        self.__logger = logging.getLogger('uni3_requests_cache')
        self.pantheon = pantheon
        self.__requests = {}
        self.__api = api
        self.__redis = None
        self.__redis_batch_executor = None
        self.__redis_request_key = pantheon.process_name + '.requests'
        self.__finalised_requests_cleanup_after_s = int(
            config['finalised_requests_cleanup_after_s'])
        self.__add_in_redis_failed_requests_queue = deque()

    async def start(self, transaction_status_poller: TransactionsStatusPoller):
        self.__redis = self.pantheon.get_aioredis_connection()
        self.__redis_batch_executor = RedisBatchExecutor(self.pantheon, self.__logger, self.__redis,
                                                         write_interval=timedelta(seconds=5), write_callback=None)
        await self.__load_requests(transaction_status_poller)
        self.pantheon.spawn(self.__finalised_requests_cleanup())
        self.pantheon.spawn(self.__retry_failed_add_in_redis())

    def add(self, request: Request):
        if (self.does_exist(request.client_request_id)):
            raise RuntimeError(
                f'{request.client_request_id} already exists in request cache')
        self.__requests[request.client_request_id] = request
        self.add_or_update_request_in_redis(request.client_request_id)

    def does_exist(self, client_request_id: str) -> bool:
        if (client_request_id in self.__requests):
            return True
        return False

    def get(self, client_request_id: str) -> Optional[Request]:
        if (client_request_id in self.__requests):
            return self.__requests[client_request_id]
        return None

    def get_all(self, request_type: RequestType) -> List[Request]:
        requests_list = []
        for request in self.__requests.values():
            if (request.request_type == request_type):
                requests_list.append(request)
        return requests_list

    def finalise_request(self, client_request_id: str, request_status: RequestStatus):
        request = self.get(client_request_id)
        if (request):
            request.finalise_request(request_status)
            self.add_or_update_request_in_redis(client_request_id)
        else:
            self.__logger.error(
                f'Not finalising request with client_request_id={client_request_id} as not found')

    def add_or_update_request_in_redis(self, client_request_id: str):
        request = self.get(client_request_id)
        if (request):
            try:
                self.__redis_batch_executor.execute(
                    'HSET', self.__redis_request_key, client_request_id, json.dumps(request.to_dict()))
            except Exception as ex:
                self.__logger.exception(
                    f'Failed to add client_request_id={client_request_id} in redis: %r. Will retry.', ex)
                self.__add_in_redis_failed_requests_queue.append(
                    client_request_id)
        else:
            self.__logger.error(
                f'Not adding in redis as client_request_id={client_request_id} not found')

    def __delete_request(self, client_request_id: str):
        try:
            self.__redis_batch_executor.execute(
                'HDEL', self.__redis_request_key, client_request_id)
            self.__requests.pop(client_request_id)
        except Exception as ex:
            self.__logger.exception(
                f'Failed to delete client_request_id={client_request_id} from cache: %r', ex)

    async def __load_requests(self, transaction_status_poller: TransactionsStatusPoller):
        self.__logger.info(
            f'Loading requests from redis: {self.__redis_request_key}')

        start = time.time()
        requests_dict = {}
        max_nonce = -1

        while(True):
            try:
                if await self.__redis.exists(self.__redis_request_key):
                    requests_dict = await self.__redis.hgetall(self.__redis_request_key)
                break
            except Exception as ex:
                self.__logger.error(
                    "Error loading requests from redis for key:'%s', err: %r. Retrying in 5s.",
                    self.__redis_request_key, ex)
                await self.pantheon.sleep(5)

        for request_str in requests_dict.values():
            try:
                request_json = json.loads(request_str)
                if (request_json['request_type'] == RequestType.ORDER.name):
                    request = OrderRequest.from_json(request_json)
                elif (request_json['request_type'] == RequestType.TRANSFER.name):
                    request = TransferRequest.from_json(request_json)
                else:
                    request = ApproveRequest.from_json(request_json)

                self.add(request)
                for tx_hash, request_type in request.tx_hashes:
                    transaction_status_poller.add_for_polling(
                        tx_hash, request.client_request_id, RequestType[request_type])

                max_nonce = max(max_nonce, request.nonce)

            except Exception as e:
                self.__logger.error(
                    "Error loading request from redis, err: %r, skipping:'%s'", e, request_str)

        self.__api.initialize_starting_nonce(max_nonce + 1)

        self.__logger.info("Loaded %d requests from redis in %dms", len(self.__requests),
                           round((time.time() - start) * 1000))

    async def __finalised_requests_cleanup(self):
        self.__logger.debug(
            f'Starting poller for clearing up requests finalised {self.__finalised_requests_cleanup_after_s}s earlier')

        while True:
            self.__logger.debug('Polling for finalised requests cleanup')
            for request in list(self.__requests.values()):
                if (self.__can_delete_request_now(request)):
                    self.__delete_request(request.client_request_id)

            await self.pantheon.sleep(25)

    async def __retry_failed_add_in_redis(self):
        self.__logger.debug(
            f'Starting poller to retry failed add in redis requests')

        while True:
            self.__logger.debug('Polling to retry failed add in redis requests')
            temp = self.__add_in_redis_failed_requests_queue
            self.__add_in_redis_failed_requests_queue = deque()
            while len(temp) > 0:
                client_request_id = temp.pop()
                request = self.get(client_request_id)
                if (request and not self.__can_delete_request_now(request)):
                    self.add_or_update_request_in_redis(client_request_id)

            await self.pantheon.sleep(10)

    def __can_delete_request_now(self, request: Request):
        now_ms = int(time.time() * 1000)
        if (request.is_finalised() and request.finalised_at_ms + self.__finalised_requests_cleanup_after_s * 1000 < now_ms):
            return True
        return False
