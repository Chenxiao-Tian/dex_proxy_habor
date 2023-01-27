import logging

from pantheon import Pantheon
from pyutils.exchange_apis.uniswapV3_api import RequestType, RequestStatus, UniswapV3Api
from web3.exceptions import TransactionNotFound


class TransactionsStatusPoller:
    def __init__(self, pantheon: Pantheon, api: UniswapV3Api, request_cache,
                 request_status_update_handler, config):
        self.__logger = logging.getLogger('uni3_transactions_status_poller')
        self.pantheon = pantheon
        self.__api = api
        self.__request_cache = request_cache
        self.__request_status_update_handler = request_status_update_handler
        self.__tx_hash_to_client_rid_and_request_type = {}
        self.__poll_interval_s = config['poll_interval_s']

    async def start(self):
        self.pantheon.spawn(self.__poll_tx_for_status())
        
    def add_for_polling(self, tx_hash: str, client_request_id: str, request_type: RequestType):
        self.__tx_hash_to_client_rid_and_request_type[tx_hash] = (client_request_id, request_type)
        
    async def poll_for_status(self, tx_hash: str):
        if (tx_hash in self.__tx_hash_to_client_rid_and_request_type):
            await self.__poll_tx({tx_hash: self.__tx_hash_to_client_rid_and_request_type[tx_hash]})
        else:
            self.__logger.error(f'No request found for the tx_hash={tx_hash}')

    async def __poll_tx_for_status(self):
        self.__logger.debug(
            f'Start polling for transaction status every {self.__poll_interval_s}s')

        while True:
            self.__logger.debug('Polling status for transactions')
            await self.__poll_tx(self.__tx_hash_to_client_rid_and_request_type)
            await self.pantheon.sleep(self.__poll_interval_s)

    async def __poll_tx(self, tx_hash_to_client_r_id_and_request_type: dict):
        for tx_hash in list(tx_hash_to_client_r_id_and_request_type.keys()):
            client_request_id, request_type = tx_hash_to_client_r_id_and_request_type[tx_hash]
            request = self.__request_cache.get(client_request_id)
            if (request is None):
                tx_hash_to_client_r_id_and_request_type.pop(tx_hash)
            elif (request.is_finalised()):
                tx_hash_to_client_r_id_and_request_type.pop(tx_hash)
            else:
                try:
                    tx = self.__api.get_transaction_receipt(tx_hash)
                    if (tx is not None):
                        status = tx['status']
                        if (request_type == RequestType.CANCEL):
                            request_status = RequestStatus.CANCELED
                        else:
                            if (status == 1):
                                request_status = RequestStatus.SUCCEEDED
                            else:
                                request_status = RequestStatus.FAILED

                        self.__request_cache.finalise_request(
                            client_request_id, request_status)
                        await self.__request_status_update_handler(client_request_id)

                except Exception as ex:
                    if not isinstance(ex, TransactionNotFound):
                        self.__logger.exception(
                            f'Error polling tx_hash: {tx_hash} for client_request_id={client_request_id}, '
                            f'request_type={request_type}: %r', ex)
