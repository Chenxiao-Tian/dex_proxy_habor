import json
import logging
import time
from datetime import timedelta
from collections import deque
from typing import Dict, List, Optional

from pantheon import Pantheon

from utils.redis_batch_executor import RedisBatchExecutor

from pyutils.exchange_apis.dex_common import (
    RequestType,
    Request,
    RequestStatus,
    OrderRequest,
    TransferRequest,
    ApproveRequest,
    WrapUnwrapRequest
)

from .transactions_status_poller import TransactionsStatusPoller


class RequestsCache:
    def __init__(self, pantheon: Pantheon, config):
        self.__logger = logging.getLogger('requests_cache')
        self.pantheon = pantheon
        self.__requests: Dict[str, Request] = {}
        self.__redis = None
        self.__redis_batch_executor = None
        self.__redis_request_key = pantheon.process_name + '.requests'
        self.__finalised_requests_cleanup_after_s = int(
            config['finalised_requests_cleanup_after_s'])
        self.__pending_add_in_redis = deque()

        # TODO: probably switch default to False in future
        self.__store_in_redis: bool = config.get("store_in_redis", True)

    async def start(self, transactions_status_poller: TransactionsStatusPoller):
        if self.__store_in_redis:
            self.__redis = self.pantheon.get_aioredis_connection()
            self.__redis_batch_executor = RedisBatchExecutor(self.pantheon, self.__logger, self.__redis,
                                                            write_interval=timedelta(seconds=5), write_callback=None)

            await self.__load_requests(transactions_status_poller)
            self.pantheon.spawn(self.__retry_failed_add_in_redis())

        self.pantheon.spawn(self.__finalised_requests_cleanup())

    def add(self, request: Request):
        if request.client_request_id in self.__requests:
            raise RuntimeError(
                f'{request.client_request_id} already exists in request cache')
        self.__requests[request.client_request_id] = request
        self.maybe_add_or_update_request_in_redis(request.client_request_id)

    def get(self, client_request_id: str) -> Optional[Request]:
        return self.__requests.get(client_request_id, None)

    def get_all(self, request_type: RequestType = None) -> List[Request]:
        requests_list = []
        for request in self.__requests.values():
            if (not request.is_finalised()) and (request_type == None or request.request_type == request_type):
                requests_list.append(request)
        return requests_list

    def get_max_nonce(self, request_filter=None) -> int:
        if request_filter is not None:
            requests = filter(request_filter, self.__requests.values())
        else:
            requests = self.__requests.values()
        return max([request.nonce if request.nonce else -1 for request in requests], default=-1)

    def finalise_request(self, client_request_id: str, request_status: RequestStatus):
        request = self.get(client_request_id)
        if request:
            request.finalise_request(request_status)
            self.maybe_add_or_update_request_in_redis(client_request_id)
        else:
            self.__logger.error(
                f'Not finalising request with client_request_id={client_request_id} as not found')

    def maybe_add_or_update_request_in_redis(self, client_request_id: str):
        if not self.__store_in_redis:
            return

        request = self.get(client_request_id)
        if request:
            try:
                self.__redis_batch_executor.execute(
                    'HSET', self.__redis_request_key, client_request_id, json.dumps(request.to_dict()))
            except Exception as ex:
                self.__logger.exception(
                    f'Failed to add client_request_id={client_request_id} in redis: %r. Will retry.', ex)
                self.__pending_add_in_redis.append(client_request_id)
        else:
            self.__logger.error(
                f'Not adding in redis as client_request_id={client_request_id} not found')

    def __delete_request(self, client_request_id: str):
        try:
            if self.__store_in_redis:
                self.__redis_batch_executor.execute(
                    'HDEL', self.__redis_request_key, client_request_id)

            self.__requests.pop(client_request_id)
        except Exception as ex:
            self.__logger.exception(
                f'Failed to delete client_request_id={client_request_id} from cache: %r', ex)

    async def __load_requests(self, transactions_status_poller: TransactionsStatusPoller):
        self.__logger.info(
            f'Loading requests from redis: {self.__redis_request_key}')

        start = time.time()
        requests_dict = {}

        while True:
            try:
                if await self.__redis.exists(self.__redis_request_key):
                    requests_dict = await self.__redis.hgetall(self.__redis_request_key)
                break
            except Exception as ex:
                self.__logger.error("Error loading requests from redis for key:'%s', err: %r. Retrying in 5s.",
                                    self.__redis_request_key, ex)
                await self.pantheon.sleep(5)

        for request_str in requests_dict.values():
            try:
                self.__logger.debug(f'Loading request {request_str}')
                request_json = json.loads(request_str)
                if request_json['request_type'] == RequestType.ORDER.name:
                    request = OrderRequest.from_json(request_json)
                elif request_json['request_type'] == RequestType.TRANSFER.name:
                    request = TransferRequest.from_json(request_json)
                elif request_json['request_type'] == RequestType.APPROVE.name:
                    request = ApproveRequest.from_json(request_json)
                elif request_json['request_type'] == RequestType.WRAP_UNWRAP.name:
                    request = WrapUnwrapRequest.from_json(request_json)
                else:
                    assert False

                if request.nonce:
                    self.__requests[request.client_request_id] = request
                    for tx_hash, request_type in request.tx_hashes:
                        if tx_hash is not None:
                            transactions_status_poller.add_for_polling(tx_hash,
                                                                       request.client_request_id,
                                                                       RequestType[request_type])

            except Exception as e:
                self.__logger.error(
                    "Error loading request from redis, err: %r, skipping:'%s'", e, request_str)

        self.__logger.info("Loaded %d requests from redis in %dms", len(
            self.__requests), round((time.time() - start) * 1000))

    async def __finalised_requests_cleanup(self):
        self.__logger.debug(
            f'Starting poller for clearing up requests finalised {self.__finalised_requests_cleanup_after_s}s earlier')

        while True:
            self.__logger.debug('Polling for finalised requests cleanup')
            for request in list(self.__requests.values()):
                if self.__can_delete_request_now(request):
                    self.__delete_request(request.client_request_id)

            await self.pantheon.sleep(25)

    # retries adding requests in redis which failed to be added in redis in all previous attempts
    async def __retry_failed_add_in_redis(self):
        self.__logger.debug(
            f'Starting poller to retry adding requests in redis')

        while True:
            self.__logger.debug('Polling to retry adding requests in redis')
            temp = self.__pending_add_in_redis
            self.__pending_add_in_redis = deque()
            while len(temp) > 0:
                client_request_id = temp.pop()
                request = self.get(client_request_id)
                if request and not self.__can_delete_request_now(request):
                    self.maybe_add_or_update_request_in_redis(client_request_id)

            await self.pantheon.sleep(10)

    def __can_delete_request_now(self, request: Request):
        now_ms = int(time.time() * 1000)
        if request.is_finalised() and \
                request.finalised_at_ms + self.__finalised_requests_cleanup_after_s * 1000 < now_ms:
            return True
        return False
